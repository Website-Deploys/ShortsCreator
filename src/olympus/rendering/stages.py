"""The twenty Rendering Engine stages.

Each stage is an isolated, replaceable unit behind the
:class:`RenderStageAnalyzer` contract; none imports another. Together they take
the Editing Engine's timelines and the source media and execute them into real
encoded MP4s, then verify the output and publish the render manifest.

Honesty rules (enforced by construction):
- The load/validate/build/apply stages are deterministic *planning* over the real
  timeline - they need no renderer and run for real, producing the exact render
  plan (segments, cuts, zooms, crops, transitions, captions, music, audio mix).
- The execution stages (preview, full-resolution render, verification) require a
  working renderer; when FFmpeg (or another backend) is unavailable they report
  ``UNAVAILABLE`` with the exact reason - never a fabricated file.
- The manifest is published only from *real* rendered files; if none were
  produced, the manifest stage is ``UNAVAILABLE`` (it never invents a manifest).
The engine performs execution only; it never changes the creative decisions.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from olympus.domain.contracts.render_pipeline import (
    RenderOutcome,
    RenderProgressReporter,
    RenderStageAnalyzer,
    RenderStageContext,
)
from olympus.domain.contracts.rendering import ClipRenderSpec, RendererUnavailableError
from olympus.domain.entities.rendering import RenderManifest, RenderStatus
from olympus.integration import clip_intelligence as CI  # noqa: N812 (module alias is intentional)
from olympus.metadata import (
    UPLOAD_METADATA_V2_VERSION,
    generate_upload_metadata,
    unavailable_upload_metadata,
)
from olympus.platform.config import get_settings
from olympus.platform.errors import ExternalServiceError
from olympus.rendering import command as C  # noqa: N812 (module alias is intentional)
from olympus.rendering import manifest as M  # noqa: N812 (module alias is intentional)
from olympus.safety import CopyrightSafetyChecker
from olympus.utils import new_id, utc_now

_NO_TIMELINES = (
    "No edit timelines are available from the Editing Engine, so there is nothing "
    "to render. (The Editing Engine produced zero timelines, or has not completed.)"
)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _source_key(timeline: dict[str, Any]) -> str:
    source = timeline.get("source_video")
    return str((source or {}).get("storage_key", "")) if isinstance(source, dict) else ""


def _clip_id(timeline: dict[str, Any]) -> str:
    return str(timeline.get("clip_id", ""))


async def _link_ingestion_record(ctx: RenderStageContext) -> dict[str, Any]:
    ingestion_id = ctx.project.link_ingestion_id
    if not ingestion_id:
        return {}
    key = f"link_ingestions/{ingestion_id}/status.json"
    if not await ctx.storage.exists(key):
        return {}
    try:
        payload = json.loads((await ctx.storage.get(key)).decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_presence(ctx: RenderStageContext) -> dict[str, bool]:
    data = ctx.render_data("validate_source_assets") or {}
    return {
        str(s.get("clip_id")): bool(s.get("present"))
        for s in data.get("sources", [])
        if isinstance(s, dict)
    }


def _renderer_unavailable_reason(ctx: RenderStageContext) -> str | None:
    availability = ctx.renderer.availability()
    return None if availability.available else (availability.reason or "renderer unavailable")


def _caption_intelligence(timeline: dict[str, Any]) -> dict[str, Any]:
    metadata = timeline.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    editing = metadata.get("editing_v2")
    editing = editing if isinstance(editing, dict) else {}
    intelligence = metadata.get("caption_intelligence_v2") or editing.get(
        "caption_intelligence_v2"
    )
    return intelligence if isinstance(intelligence, dict) else {}


def _rendered_captions(metadata: dict[str, Any], timeline: dict[str, Any]) -> bool:
    validation = metadata.get("caption_render_validation")
    if isinstance(validation, dict):
        return bool(validation.get("captions_planned") and validation.get("passed"))
    return C.subtitles_included(timeline)


# --------------------------------------------------------------------------- #
# 1. Load Timeline
# --------------------------------------------------------------------------- #
class LoadTimelineStage(RenderStageAnalyzer):
    name = "load_timeline"
    version = "1"

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return RenderOutcome.unavailable(_NO_TIMELINES)
        loaded = [
            {
                "clip_id": _clip_id(t),
                "plan_id": t.get("plan_id"),
                "rank": t.get("rank"),
                "duration": t.get("duration"),
                "fps": t.get("fps"),
                "tracks": [trk.get("kind") for trk in t.get("tracks", []) if isinstance(trk, dict)],
                "source_key": _source_key(t),
            }
            for t in timelines
        ]
        report(1.0)
        return RenderOutcome.completed(
            {
                "timeline_count": len(loaded),
                "timeline_version": ctx.editing_version(),
                "timelines": loaded,
                "logs": [f"loaded {len(loaded)} edit timeline(s) from the Editing Engine"],
            }
        )


# --------------------------------------------------------------------------- #
# 2. Validate Timeline
# --------------------------------------------------------------------------- #
class ValidateTimelineStage(RenderStageAnalyzer):
    name = "validate_timeline"
    version = "3"
    depends_on = ("load_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return RenderOutcome.unavailable(_NO_TIMELINES)
        clips: list[dict[str, Any]] = []
        for t in timelines:
            issues: list[str] = []
            duration = float(t.get("duration") or 0.0)
            if duration <= 0:
                issues.append("timeline duration is not positive")
            cues = C.caption_cues(t)
            for cue in cues:
                if cue["end"] < cue["start"]:
                    issues.append("a caption ends before it starts")
                    break
            for cue in cues:
                if cue["start"] < -0.001 or cue["end"] > duration + 0.5:
                    issues.append("a caption falls outside the clip duration")
                    break
            readability = _caption_intelligence(t).get("caption_readability_validation")
            if isinstance(readability, dict) and readability.get("passed") is False:
                issues.append("caption readability validation failed")
            motion = C.motion_intelligence(t)
            motion_safety = motion.get("motion_safety_validation")
            motion_safety = motion_safety if isinstance(motion_safety, dict) else {}
            motion_decision = motion.get("decision")
            motion_decision = motion_decision if isinstance(motion_decision, dict) else {}
            for effect in C.motion_effects(t):
                start = float(effect.get("start_time") or effect.get("start") or 0.0)
                end = float(effect.get("end_time") or effect.get("end") or 0.0)
                if start < 0 or end <= start or end > duration + 0.001:
                    issues.append("a motion effect falls outside the clip duration")
                    break
            if (
                motion_decision.get("should_apply_motion") is True
                and motion_safety.get("passed") is not True
            ):
                issues.append("motion safety validation failed")
            clips.append(
                {
                    "clip_id": _clip_id(t),
                    "valid": not issues,
                    "issues": issues,
                    "caption_readability_validation": readability,
                    "motion_safety_validation": motion_safety,
                }
            )
        report(1.0)
        return RenderOutcome.completed(
            {
                "valid": all(c["valid"] for c in clips),
                "clips": clips,
                "logs": [f"validated {len(clips)} timeline(s)"],
            }
        )


# --------------------------------------------------------------------------- #
# 3. Validate Source Assets
# --------------------------------------------------------------------------- #
class ValidateSourceAssetsStage(RenderStageAnalyzer):
    name = "validate_source_assets"
    version = "1"
    depends_on = ("load_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return RenderOutcome.unavailable(_NO_TIMELINES)
        sources: list[dict[str, Any]] = []
        for t in timelines:
            key = _source_key(t)
            present = bool(key) and await ctx.storage.exists(key)
            sources.append({"clip_id": _clip_id(t), "storage_key": key, "present": present})
        missing = [s["clip_id"] for s in sources if not s["present"]]
        report(1.0)
        return RenderOutcome.completed(
            {
                "sources": sources,
                "missing": missing,
                "all_present": not missing,
                "logs": [f"checked {len(sources)} source asset(s); {len(missing)} missing"],
            }
        )


# --------------------------------------------------------------------------- #
# 4. Prepare Working Directory
# --------------------------------------------------------------------------- #
class PrepareWorkingDirectoryStage(RenderStageAnalyzer):
    name = "prepare_working_directory"
    version = "1"

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        prefix = f"render/{ctx.project.id}/work/"
        report(1.0)
        return RenderOutcome.completed(
            {
                "working_prefix": prefix,
                "output_prefix": f"render/{ctx.project.id}/clips/",
                "logs": [f"working directory prepared at {prefix}"],
            }
        )


# --------------------------------------------------------------------------- #
# 5-6. Build video / audio timelines
# --------------------------------------------------------------------------- #
class BuildVideoTimelineStage(RenderStageAnalyzer):
    name = "build_video_timeline"
    version = "1"
    depends_on = ("validate_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        clips = [{"clip_id": _clip_id(t), "segments": C.video_segments(t)} for t in ctx.timelines()]
        report(1.0)
        return RenderOutcome.completed(
            {"clips": clips, "logs": [f"built video timeline for {len(clips)} clip(s)"]}
        )


class BuildAudioTimelineStage(RenderStageAnalyzer):
    name = "build_audio_timeline"
    version = "1"
    depends_on = ("validate_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        clips = [{"clip_id": _clip_id(t), "segments": C.audio_segments(t)} for t in ctx.timelines()]
        report(1.0)
        return RenderOutcome.completed(
            {"clips": clips, "logs": [f"built audio timeline for {len(clips)} clip(s)"]}
        )


# --------------------------------------------------------------------------- #
# 7-13. Apply edits (deterministic translation of timeline -> render ops)
# --------------------------------------------------------------------------- #
class _ApplyStage(RenderStageAnalyzer):
    """Base for the deterministic 'apply' planning stages."""

    op_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] = staticmethod(lambda timeline: [])
    op_key = "ops"
    depends_on = ("build_video_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        clips: list[dict[str, Any]] = []
        total = 0
        for t in ctx.timelines():
            ops = type(self).op_fn(t)
            total += len(ops)
            clips.append({"clip_id": _clip_id(t), "count": len(ops), self.op_key: ops})
        report(1.0)
        return RenderOutcome.completed(
            {"clips": clips, "total": total, "logs": [f"prepared {total} {self.op_key}"]}
        )


class ApplyJumpCutsStage(_ApplyStage):
    name = "apply_jump_cuts"
    version = "1"
    op_fn = staticmethod(C.jump_cut_ops)
    op_key = "jump_cuts"


class ApplyZoomsStage(_ApplyStage):
    name = "apply_zooms"
    version = "2"
    op_fn = staticmethod(C.zoom_ops)
    op_key = "zooms"


class ApplyCropsStage(RenderStageAnalyzer):
    name = "apply_crops"
    version = "2"
    depends_on = ("build_video_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        clips = [{"clip_id": _clip_id(t), "crop": C.crop_op(t)} for t in ctx.timelines()]
        report(1.0)
        return RenderOutcome.completed(
            {"clips": clips, "logs": [f"prepared crop for {len(clips)} clip(s)"]}
        )


class ApplyTransitionsStage(_ApplyStage):
    name = "apply_transitions"
    version = "1"
    op_fn = staticmethod(C.transition_ops)
    op_key = "transitions"


class ApplyCaptionsStage(RenderStageAnalyzer):
    name = "apply_captions"
    version = "2"
    depends_on = ("build_video_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        clips: list[dict[str, Any]] = []
        for t in ctx.timelines():
            cues = C.caption_cues(t)
            intelligence = _caption_intelligence(t)
            style = intelligence.get("style_decision")
            timing = intelligence.get("caption_timing_quality")
            readability = intelligence.get("caption_readability_validation")
            clips.append(
                {
                    "clip_id": _clip_id(t),
                    "caption_count": len(cues),
                    "subtitles_included": bool(cues),
                    "style": style if isinstance(style, dict) else {},
                    "timing_quality": timing if isinstance(timing, dict) else {},
                    "readability_validation": (
                        readability if isinstance(readability, dict) else {}
                    ),
                    "render_status": "planned" if cues else "disabled_or_unavailable",
                }
            )
        report(1.0)
        return RenderOutcome.completed(
            {"clips": clips, "logs": [f"prepared captions for {len(clips)} clip(s)"]}
        )


class ApplyBrollStage(_ApplyStage):
    name = "apply_broll"
    version = "1"
    op_fn = staticmethod(C.broll_ops)
    op_key = "broll"


class ApplyMusicStage(RenderStageAnalyzer):
    name = "apply_music"
    version = "2"
    depends_on = ("build_audio_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        clips: list[dict[str, Any]] = []
        for t in ctx.timelines():
            ops = C.music_ops(t)
            clips.append(
                {"clip_id": _clip_id(t), "music_count": len(ops), "music_included": bool(ops)}
            )
        report(1.0)
        return RenderOutcome.completed(
            {
                "clips": clips,
                "note": "music cues and Music Intelligence decisions come from the timeline; "
                "the renderer resolves only verified safe local assets and reports truth.",
                "logs": [f"prepared music for {len(clips)} clip(s)"],
            }
        )


class AudioMixingStage(RenderStageAnalyzer):
    name = "audio_mixing"
    version = "2"
    depends_on = ("build_audio_timeline", "apply_music")

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        clips = [{"clip_id": _clip_id(t), "mix": C.audio_mix_plan(t)} for t in ctx.timelines()]
        report(1.0)
        return RenderOutcome.completed(
            {"clips": clips, "logs": [f"prepared audio mix for {len(clips)} clip(s)"]}
        )


# --------------------------------------------------------------------------- #
# 15-16. Render execution (require a working renderer)
# --------------------------------------------------------------------------- #
class _RenderExecutionStage(RenderStageAnalyzer):
    """Shared execution logic for the preview and full-resolution render stages."""

    preview = False
    version = "2"

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        timelines = ctx.timelines()
        if not timelines:
            return RenderOutcome.unavailable(_NO_TIMELINES)
        reason = _renderer_unavailable_reason(ctx)
        if reason:
            return RenderOutcome.unavailable(
                f"Cannot render: {reason}. The render plan was built, but no MP4 can be "
                "produced without a working renderer; nothing is fabricated."
            )
        presence = _source_presence(ctx)
        outputs: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        logs: list[str] = []
        s = ctx.settings
        safety_checker = CopyrightSafetyChecker(get_settings().copyright_safety)
        link_record = await _link_ingestion_record(ctx)
        project_data = ctx.project.to_dict()
        for t in timelines:
            cid = _clip_id(t)
            if not presence.get(cid, False):
                skipped.append({"clip_id": cid, "reason": "source asset missing"})
                continue
            pre_render_safety = safety_checker.check(
                project=project_data,
                clip_id=cid,
                timeline=t,
                link_record=link_record,
                assessment_phase="pre_render",
            )
            if safety_checker.should_block(pre_render_safety):
                skipped.append(
                    {
                        "clip_id": cid,
                        "reason": "copyright_safety_blocked",
                        "copyright_safety_v2": pre_render_safety,
                    }
                )
                continue
            spec = ClipRenderSpec(
                clip_id=cid,
                source_key=_source_key(t),
                output_key=self._output_key(ctx, cid),
                timeline=t,
                width=s.preview_width if self.preview else s.width,
                height=s.preview_height if self.preview else s.height,
                fps=s.fps,
                video_bitrate_kbps=s.preview_bitrate_kbps if self.preview else s.video_bitrate_kbps,
                audio_bitrate_kbps=s.audio_bitrate_kbps,
                preview=self.preview,
            )
            try:
                out = await ctx.renderer.render_clip(spec, ctx.storage)
            except RendererUnavailableError as exc:
                return RenderOutcome.unavailable(f"Cannot render: {exc.reason}")
            except ExternalServiceError as exc:
                logs.append(f"[error] clip {cid}: {exc}")
                details = exc.details if isinstance(exc.details, dict) else {}
                stderr_tail = details.get("stderr_tail")
                ffmpeg_tail = (
                    [str(line) for line in stderr_tail] if isinstance(stderr_tail, list) else []
                )
                logs.extend(f"[ffmpeg] {line}" for line in ffmpeg_tail)
                command_summary = (
                    details.get("command_summary")
                    if isinstance(details.get("command_summary"), dict)
                    else {}
                )
                resource_hint = str(details.get("resource_hint") or "")
                stage_name = str(details.get("stage_name") or self.name)
                if command_summary:
                    logs.append(f"[ffmpeg] command_summary={command_summary}")
                if resource_hint:
                    logs.append(f"[ffmpeg] resource_hint={resource_hint}")
                tail_reason = " | ".join(ffmpeg_tail[-3:])
                reason = f"{exc} {tail_reason}".strip() if tail_reason else str(exc)
                skipped.append(
                    {
                        "clip_id": cid,
                        "reason": reason,
                        "stage_name": stage_name,
                        "stderr_tail": ffmpeg_tail,
                        "command_summary": command_summary,
                        "resource_exhaustion": details.get("resource_exhaustion") is True,
                        "resource_hint": resource_hint,
                    }
                )
                continue
            logs.extend(out.logs)
            rendered = self._output_dict(t, out)
            metadata = rendered.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            metadata["copyright_safety_pre_render"] = {
                "report_id": pre_render_safety["report_id"],
                "risk_level": pre_render_safety["overall"]["risk_level"],
                "blocked": False,
                "warnings": pre_render_safety["result"]["warnings"],
            }
            metadata["copyright_safety_v2"] = safety_checker.check(
                project=project_data,
                clip_id=cid,
                timeline=t,
                render_metadata=metadata,
                render_output=rendered,
                link_record=link_record,
                assessment_phase="preview_output" if self.preview else "final_output",
            )
            metadata["unified_clip_intelligence"] = CI.unified_clip_intelligence(
                clip=t,
                editing_v2=CI.as_dict(metadata.get("editing_v2")),
                render_metadata=metadata,
                render_output=rendered,
            )
            rendered["metadata"] = metadata
            outputs.append(rendered)
        if not outputs and skipped:
            return RenderOutcome.failed(
                f"All clips failed to render: {skipped[0]['reason']}",
                data={
                    "clips": outputs,
                    "rendered_count": 0,
                    "skipped": skipped,
                    "renderer": ctx.renderer.name,
                    "preview": self.preview,
                    "logs": logs,
                },
            )
        report(1.0)
        return RenderOutcome.completed(
            {
                "clips": outputs,
                "rendered_count": len(outputs),
                "skipped": skipped,
                "renderer": ctx.renderer.name,
                "preview": self.preview,
                "logs": logs or [f"rendered {len(outputs)} clip(s)"],
            }
        )

    def _output_key(self, ctx: RenderStageContext, clip_id: str) -> str:
        if self.preview:
            return f"render/{ctx.project.id}/work/preview_{clip_id}.mp4"
        return f"render/{ctx.project.id}/clips/{clip_id}.mp4"

    @staticmethod
    def _output_dict(timeline: dict[str, Any], out: Any) -> dict[str, Any]:
        metadata = dict(out.metadata or {})
        subtitles_included = _rendered_captions(metadata, timeline)
        metadata["unified_clip_intelligence"] = CI.unified_clip_intelligence(
            clip=timeline,
            editing_v2=CI.as_dict(metadata.get("editing_v2")),
            render_metadata=metadata,
            render_output={
                "clip_id": out.clip_id,
                "output_key": out.output_key,
                "plan_id": timeline.get("plan_id"),
                "duration": out.duration,
                "subtitles_included": subtitles_included,
            },
        )
        return {
            "clip_id": out.clip_id,
            "output_key": out.output_key,
            "plan_id": timeline.get("plan_id"),
            "rank": timeline.get("rank"),
            "width": out.width,
            "height": out.height,
            "duration": out.duration,
            "fps": out.fps,
            "video_codec": out.video_codec,
            "audio_codec": out.audio_codec,
            "has_audio": out.has_audio,
            "bitrate_kbps": out.bitrate_kbps,
            "audio_sample_rate": out.audio_sample_rate,
            "size_bytes": out.size_bytes,
            "source_video": timeline.get("source_video", {}),
            "subtitles_included": subtitles_included,
            "music_included": bool(metadata.get("music_mixed")) if metadata else False,
            "metadata": metadata,
        }


class RenderPreviewStage(_RenderExecutionStage):
    name = "render_preview"
    version = "9"
    preview = True
    depends_on = ("build_video_timeline", "build_audio_timeline", "validate_source_assets")


class FullResolutionRenderStage(_RenderExecutionStage):
    name = "full_resolution_render"
    version = "9"
    preview = False
    depends_on = (
        "apply_jump_cuts",
        "apply_zooms",
        "apply_crops",
        "apply_transitions",
        "apply_captions",
        "apply_broll",
        "apply_music",
        "audio_mixing",
        "validate_source_assets",
    )


# --------------------------------------------------------------------------- #
# 17. Render Verification
# --------------------------------------------------------------------------- #
class RenderVerificationStage(RenderStageAnalyzer):
    name = "render_verification"
    version = "8"
    depends_on = ("full_resolution_render",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        render = ctx.render_data("full_resolution_render")
        if not render or not render.get("clips"):
            stage = ctx.results.get("full_resolution_render")
            reason = (stage.reason if stage else None) or "no rendered outputs exist"
            return RenderOutcome.unavailable(
                f"No rendered outputs to verify - full-resolution render did not produce files "
                f"({reason})."
            )
        timelines = {_clip_id(t): t for t in ctx.timelines()}
        s = ctx.settings
        clips: list[dict[str, Any]] = []
        for out in render["clips"]:
            cid = str(out.get("clip_id"))
            issues: list[str] = []
            checks: dict[str, Any] = {}
            present = await ctx.storage.exists(str(out.get("output_key")))
            checks["file_present"] = present
            if not present:
                issues.append("rendered file is missing from storage")
            expected = float((timelines.get(cid) or {}).get("duration") or 0.0)
            actual = float(out.get("duration") or 0.0)
            metadata = out.get("metadata") if isinstance(out.get("metadata"), dict) else {}
            sync_validation = (
                metadata.get("sync_validation")
                if isinstance(metadata.get("sync_validation"), dict)
                else None
            )
            duration_validation = (
                metadata.get("duration_validation")
                if isinstance(metadata.get("duration_validation"), dict)
                else None
            )
            checks["duration_match"] = abs(actual - expected) <= 0.15 if expected else None
            if expected and checks["duration_match"] is False:
                issues.append(f"duration {actual:.3f}s differs from timeline {expected:.3f}s")
            checks["sync_validation"] = sync_validation
            checks["duration_validation"] = duration_validation
            checks["music_validation"] = metadata.get("music_validation")
            caption_validation = (
                metadata.get("caption_render_validation")
                if isinstance(metadata.get("caption_render_validation"), dict)
                else None
            )
            checks["caption_render_validation"] = caption_validation
            multi_speaker_validation = (
                metadata.get("multi_speaker_validation")
                if isinstance(metadata.get("multi_speaker_validation"), dict)
                else None
            )
            checks["multi_speaker_validation"] = multi_speaker_validation
            motion_validation = (
                metadata.get("motion_render_validation")
                if isinstance(metadata.get("motion_render_validation"), dict)
                else None
            )
            checks["motion_render_validation"] = motion_validation
            if sync_validation and sync_validation.get("passed") is False:
                issues.append("sync validation warning")
            if duration_validation and duration_validation.get("passed") is False:
                issues.append("duration validation warning")
            if (
                caption_validation
                and caption_validation.get("captions_planned")
                and caption_validation.get("passed") is False
            ):
                issues.append("caption render validation warning")
            if multi_speaker_validation and multi_speaker_validation.get("passed") is False:
                issues.append("multi-speaker layout validation warning")
            if motion_validation and motion_validation.get("passed") is False:
                issues.append("motion render validation warning")
            checks["has_audio"] = out.get("has_audio")
            if out.get("has_audio") is False:
                issues.append("no audio stream in the rendered file")
            checks["dimensions_match"] = (
                out.get("width") == s.width and out.get("height") == s.height
            )
            clips.append({"clip_id": cid, "valid": not issues, "checks": checks, "issues": issues})
        report(1.0)
        return RenderOutcome.completed(
            {
                "valid": all(c["valid"] for c in clips),
                "clips": clips,
                "logs": [f"verified {len(clips)} rendered file(s)"],
            }
        )


# --------------------------------------------------------------------------- #
# 18. Generate Render Manifest (publishes the contract the Optimizer consumes)
# --------------------------------------------------------------------------- #
class GenerateRenderManifestStage(RenderStageAnalyzer):
    name = "generate_render_manifest"
    version = "11"
    depends_on = ("full_resolution_render", "render_verification")

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        render = ctx.render_data("full_resolution_render")
        outputs = (render or {}).get("clips") or []
        if not outputs:
            stage = ctx.results.get("full_resolution_render")
            reason = (stage.reason if stage else None) or "no MP4s were rendered"
            return RenderOutcome.unavailable(
                f"Cannot produce a render manifest: no rendered MP4s exist ({reason}). The "
                "manifest is published only from real rendered files; it is never fabricated."
            )
        now = utc_now()
        rendered_at = now.isoformat()
        render_id = new_id("render")
        renders = []
        timelines_by_clip = {_clip_id(timeline): timeline for timeline in ctx.timelines()}
        upload_metadata_settings = get_settings().upload_metadata
        for out in outputs:
            data = await ctx.storage.get(str(out["output_key"]))
            metadata = copy.deepcopy(
                out.get("metadata") if isinstance(out.get("metadata"), dict) else {}
            )
            caption_validation = metadata.get("caption_render_validation")
            if isinstance(caption_validation, dict):
                caption_validation = copy.deepcopy(caption_validation)
                captions_planned = caption_validation.get("captions_planned") is True
                manifest_confirmed = bool(captions_planned and out.get("subtitles_included"))
                caption_validation["render_manifest_confirmed"] = manifest_confirmed
                caption_validation["passed"] = bool(
                    (not captions_planned)
                    or (caption_validation.get("passed") is True and manifest_confirmed)
                )
                warnings = list(caption_validation.get("warnings") or [])
                if captions_planned and not manifest_confirmed:
                    warnings.append("Render manifest could not confirm burned-in captions.")
                caption_validation["warnings"] = list(dict.fromkeys(warnings))
                metadata["caption_render_validation"] = caption_validation

                caption_intelligence = metadata.get("caption_intelligence_v2")
                if isinstance(caption_intelligence, dict):
                    caption_intelligence = copy.deepcopy(caption_intelligence)
                    intelligence_validation = caption_intelligence.get("validation")
                    intelligence_validation = (
                        copy.deepcopy(intelligence_validation)
                        if isinstance(intelligence_validation, dict)
                        else {}
                    )
                    intelligence_validation["render_manifest_confirmed"] = manifest_confirmed
                    intelligence_validation["passed"] = bool(
                        caption_validation["passed"]
                        and intelligence_validation.get("passed", True)
                    )
                    intelligence_validation["warnings"] = list(
                        dict.fromkeys(
                            [
                                *list(intelligence_validation.get("warnings") or []),
                                *list(caption_validation.get("warnings") or []),
                            ]
                        )
                    )
                    caption_intelligence["validation"] = intelligence_validation
                    metadata["caption_intelligence_v2"] = caption_intelligence

                effects = metadata.get("render_effects_v2")
                if isinstance(effects, dict):
                    effects = copy.deepcopy(effects)
                    caption_effect = effects.get("captions")
                    if isinstance(caption_effect, dict):
                        caption_effect["included"] = manifest_confirmed
                        caption_effect["validation"] = caption_validation
                        effects["captions"] = caption_effect
                    metadata["render_effects_v2"] = effects
            motion_validation = metadata.get("motion_render_validation")
            if isinstance(motion_validation, dict):
                motion_validation = copy.deepcopy(motion_validation)
                effects_planned = int(motion_validation.get("effects_planned") or 0)
                effects_rendered = int(motion_validation.get("effects_rendered") or 0)
                manifest_confirmed = bool(
                    effects_planned > 0
                    and effects_rendered == effects_planned
                    and out.get("output_key")
                )
                motion_validation["render_manifest_confirmed"] = manifest_confirmed
                motion_validation["passed"] = bool(
                    motion_validation.get("passed") is True
                    and (effects_planned == 0 or manifest_confirmed)
                )
                warnings = list(motion_validation.get("warnings") or [])
                if effects_planned and not manifest_confirmed:
                    warnings.append("Render manifest could not confirm all planned motion effects.")
                motion_validation["warnings"] = list(dict.fromkeys(warnings))
                metadata["motion_render_validation"] = motion_validation
                motion_intelligence = metadata.get("motion_intelligence_v2")
                if isinstance(motion_intelligence, dict):
                    motion_intelligence = copy.deepcopy(motion_intelligence)
                    motion_intelligence["validation"] = copy.deepcopy(motion_validation)
                    metadata["motion_intelligence_v2"] = motion_intelligence
                effects = metadata.get("render_effects_v2")
                if isinstance(effects, dict) and isinstance(effects.get("motion"), dict):
                    effects = copy.deepcopy(effects)
                    motion_effect = copy.deepcopy(effects["motion"])
                    motion_effect["applied"] = bool(
                        manifest_confirmed and motion_validation["passed"]
                    )
                    motion_effect["render_validation"] = motion_validation
                    effects["motion"] = motion_effect
                    metadata["render_effects_v2"] = effects
            metadata["unified_clip_intelligence"] = CI.unified_clip_intelligence(
                render_metadata=metadata,
                render_output={**out, "render_id": render_id},
            )
            clip_id = str(out.get("clip_id") or "")
            artifact_key = (
                f"render/{ctx.project.id}/metadata/{clip_id}/upload_metadata_v2.json"
            )
            try:
                upload_metadata = generate_upload_metadata(
                    project_id=ctx.project.id,
                    clip_id=clip_id,
                    render_id=render_id,
                    created_at=rendered_at,
                    unified_clip_intelligence=CI.as_dict(
                        metadata.get("unified_clip_intelligence")
                    ),
                    timeline=timelines_by_clip.get(clip_id),
                    render_metadata=metadata,
                    settings=upload_metadata_settings,
                )
            except Exception as exc:
                upload_metadata = unavailable_upload_metadata(
                    project_id=ctx.project.id,
                    clip_id=clip_id,
                    render_id=render_id,
                    created_at=rendered_at,
                    reason=f"Upload metadata generation failed: {exc}",
                )
            try:
                upload_metadata["artifact"] = {
                    "status": "available",
                    "storage_key": artifact_key,
                    "version": UPLOAD_METADATA_V2_VERSION,
                }
                await ctx.storage.put(
                    artifact_key,
                    json.dumps(upload_metadata, indent=2).encode("utf-8"),
                    content_type="application/json",
                )
            except Exception as exc:
                upload_metadata["artifact"] = {
                    "status": "unavailable",
                    "storage_key": None,
                    "version": UPLOAD_METADATA_V2_VERSION,
                    "reason": f"Upload metadata artifact could not be persisted: {exc}",
                }
                upload_metadata["universal"]["warnings"] = list(
                    dict.fromkeys(
                        [
                            *upload_metadata["universal"].get("warnings", []),
                            upload_metadata["artifact"]["reason"],
                        ]
                    )
                )
            metadata["upload_metadata_v2"] = upload_metadata
            metadata["upload_metadata_v2_version"] = UPLOAD_METADATA_V2_VERSION
            metadata["unified_clip_intelligence"] = CI.unified_clip_intelligence(
                render_metadata=metadata,
                render_output={**out, "render_id": render_id},
            )
            out = {**out, "metadata": metadata}
            renders.append(
                M.rendered_video_from_output(
                    _to_clip_output(out),
                    plan_id=out.get("plan_id"),
                    rank=out.get("rank"),
                    checksum=M.checksum_bytes(data),
                    subtitles_included=bool(out.get("subtitles_included")),
                    music_included=bool(out.get("music_included")),
                    timeline_version=ctx.editing_version(),
                    rendered_at=rendered_at,
                    source_video=out.get("source_video", {}),
                    metadata=out.get("metadata", {}),
                )
            )
        manifest = RenderManifest(
            project_id=ctx.project.id,
            status=RenderStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            renderer=ctx.renderer.name,
            render_id=render_id,
            rendering_version=self.version,
            timeline_version=ctx.editing_version(),
            renders=renders,
        )
        await ctx.manifest_store.save(manifest)
        report(1.0)
        return RenderOutcome.completed(
            {
                "written": True,
                "render_id": manifest.render_id,
                "clip_count": len(renders),
                "manifest": manifest.to_dict(),
                "logs": [f"published render manifest with {len(renders)} clip(s)"],
            }
        )


def _to_clip_output(out: dict[str, Any]) -> Any:
    """Reconstruct a ClipRenderOutput-like object from persisted render data."""

    from olympus.domain.contracts.rendering import ClipRenderOutput

    return ClipRenderOutput(
        clip_id=str(out.get("clip_id")),
        output_key=str(out.get("output_key")),
        width=out.get("width"),
        height=out.get("height"),
        duration=out.get("duration"),
        fps=out.get("fps"),
        video_codec=out.get("video_codec"),
        audio_codec=out.get("audio_codec"),
        has_audio=out.get("has_audio"),
        bitrate_kbps=out.get("bitrate_kbps"),
        audio_sample_rate=out.get("audio_sample_rate"),
        size_bytes=out.get("size_bytes"),
        metadata=out.get("metadata", {}) or {},
    )


# --------------------------------------------------------------------------- #
# 19. Cleanup Temporary Files
# --------------------------------------------------------------------------- #
class CleanupTemporaryFilesStage(RenderStageAnalyzer):
    name = "cleanup_temporary_files"
    version = "2"

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        prefix = f"render/{ctx.project.id}/work/"
        keys = await ctx.storage.list_keys(prefix)
        for key in keys:
            await ctx.storage.delete(key)
        report(1.0)
        return RenderOutcome.completed(
            {"deleted_count": len(keys), "logs": [f"cleaned up {len(keys)} temporary file(s)"]}
        )


# --------------------------------------------------------------------------- #
# 20. Final Validation
# --------------------------------------------------------------------------- #
class FinalValidationStage(RenderStageAnalyzer):
    name = "final_validation"
    version = "8"
    depends_on = ("render_verification", "generate_render_manifest")

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        timeline_report = ctx.render_data("validate_timeline") or {}
        sources = ctx.render_data("validate_source_assets") or {}
        verification = ctx.render_data("render_verification") or {}
        manifest_stage = ctx.results.get("generate_render_manifest")
        rendered = bool((ctx.render_data("full_resolution_render") or {}).get("clips"))
        manifest_written = bool((ctx.render_data("generate_render_manifest") or {}).get("written"))

        unavailable = [
            {"stage": s.stage, "reason": s.reason}
            for s in ctx.results.values()
            if s.status.value == "unavailable"
        ]
        valid = bool(timeline_report.get("valid", True)) and (
            not verification or bool(verification.get("valid", True))
        )
        report(1.0)
        return RenderOutcome.completed(
            {
                "valid": valid,
                "timeline_valid": timeline_report.get("valid"),
                "sources_ok": sources.get("all_present"),
                "rendered": rendered,
                "manifest_written": manifest_written,
                "manifest_reason": manifest_stage.reason if manifest_stage else None,
                "unavailable_stages": unavailable,
                "note": "The render pipeline ran to completion. When rendering was unavailable, "
                "the plan/validation stages still produced real output and the engine reports "
                "honestly that no MP4/manifest was produced.",
                "logs": ["final validation complete"],
            }
        )
