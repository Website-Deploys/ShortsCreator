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
from olympus.platform.errors import ExternalServiceError
from olympus.rendering import command as C  # noqa: N812 (module alias is intentional)
from olympus.rendering import manifest as M  # noqa: N812 (module alias is intentional)
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
    version = "1"
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
            clips.append({"clip_id": _clip_id(t), "valid": not issues, "issues": issues})
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
    version = "1"
    op_fn = staticmethod(C.zoom_ops)
    op_key = "zooms"


class ApplyCropsStage(RenderStageAnalyzer):
    name = "apply_crops"
    version = "1"
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
    version = "1"
    depends_on = ("build_video_timeline",)

    async def run(self, ctx: RenderStageContext, report: RenderProgressReporter) -> RenderOutcome:
        clips: list[dict[str, Any]] = []
        for t in ctx.timelines():
            cues = C.caption_cues(t)
            clips.append(
                {
                    "clip_id": _clip_id(t),
                    "caption_count": len(cues),
                    "subtitles_included": bool(cues),
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
    version = "1"
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
                "note": "music cues come from the timeline; the Rendering Engine does not "
                "select music (that is the Optimization Engine's recommendation).",
                "logs": [f"prepared music for {len(clips)} clip(s)"],
            }
        )


class AudioMixingStage(RenderStageAnalyzer):
    name = "audio_mixing"
    version = "1"
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
        for t in timelines:
            cid = _clip_id(t)
            if not presence.get(cid, False):
                skipped.append({"clip_id": cid, "reason": "source asset missing"})
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
                skipped.append({"clip_id": cid, "reason": str(exc)})
                logs.append(f"[error] clip {cid}: {exc}")
                continue
            logs.extend(out.logs)
            outputs.append(self._output_dict(t, out))
        if not outputs and skipped:
            return RenderOutcome.failed(f"All clips failed to render: {skipped[0]['reason']}")
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
            "subtitles_included": C.subtitles_included(timeline),
            "music_included": C.music_included(timeline),
        }


class RenderPreviewStage(_RenderExecutionStage):
    name = "render_preview"
    version = "1"
    preview = True
    depends_on = ("build_video_timeline", "build_audio_timeline", "validate_source_assets")


class FullResolutionRenderStage(_RenderExecutionStage):
    name = "full_resolution_render"
    version = "1"
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
    version = "1"
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
            checks["duration_match"] = (
                abs(actual - expected) <= max(1.0, expected * 0.1) if expected else None
            )
            if expected and checks["duration_match"] is False:
                issues.append(f"duration {actual:.1f}s differs from timeline {expected:.1f}s")
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
    version = "1"
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
        renders = []
        for out in outputs:
            data = await ctx.storage.get(str(out["output_key"]))
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
                )
            )
        manifest = RenderManifest(
            project_id=ctx.project.id,
            status=RenderStatus.COMPLETED,
            created_at=now,
            updated_at=now,
            renderer=ctx.renderer.name,
            render_id=new_id("render"),
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
    )


# --------------------------------------------------------------------------- #
# 19. Cleanup Temporary Files
# --------------------------------------------------------------------------- #
class CleanupTemporaryFilesStage(RenderStageAnalyzer):
    name = "cleanup_temporary_files"
    version = "1"

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
    version = "1"
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
