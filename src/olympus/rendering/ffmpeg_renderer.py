"""The FFmpeg clip renderer - real execution, honest availability.

Implements the :class:`ClipRenderer` port using FFmpeg. It probes for the FFmpeg
(and ffprobe) binaries and reports availability honestly; when they are absent it
raises :class:`RendererUnavailableError` with the exact reason rather than
fabricating output. When present, it executes the deterministic FFmpeg command
built from the timeline (trim, reframe, caption burn, encode), measures the real
output with ffprobe, and writes the encoded bytes to storage.

FFmpeg is never hardcoded into business logic: the pipeline depends only on the
``ClipRenderer`` abstraction, so GPU, cloud, or distributed renderers can replace
this without touching any stage.
"""

from __future__ import annotations

import asyncio
import copy
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from olympus.domain.contracts.rendering import (
    ClipRenderer,
    ClipRenderOutput,
    ClipRenderSpec,
    RendererAvailability,
    RendererUnavailableError,
)
from olympus.domain.contracts.storage import StoragePort
from olympus.integration import clip_intelligence as CI  # noqa: N812 (module alias is intentional)
from olympus.music import build_music_validation
from olympus.platform.errors import ExternalServiceError
from olympus.platform.logging import get_logger
from olympus.rendering import command as C  # noqa: N812 (module alias is intentional)
from olympus.rendering.assets import resolve_assets

log = get_logger(__name__)

_MAX_LOG_LINES = 40

# Bounded execution timeouts so a hung or runaway FFmpeg can never block a worker
# forever (the worker's heartbeat keepalive would otherwise mask the stall, so the
# health monitor would never recover it). On timeout ``subprocess.run`` kills the
# child process, preventing a zombie FFmpeg.
_RENDER_TIMEOUT_SECONDS = 1800.0
_PROBE_TIMEOUT_SECONDS = 60.0


class FfmpegClipRenderer(ClipRenderer):
    """Render a clip's timeline to a real MP4 via FFmpeg."""

    name = "ffmpeg"

    def __init__(
        self,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        asset_root: str | None = None,
    ) -> None:
        self._ffmpeg = ffmpeg_binary
        self._ffprobe = ffprobe_binary
        self._asset_root = asset_root
        self._music_usage_counts: dict[str, dict[str, int]] = {}

    def availability(self) -> RendererAvailability:
        ffmpeg_path = shutil.which(self._ffmpeg)
        if ffmpeg_path is None:
            return RendererAvailability(
                available=False,
                renderer=self.name,
                reason=(
                    f"FFmpeg binary {self._ffmpeg!r} was not found on PATH. Install FFmpeg to "
                    "enable rendering; no MP4 can be produced without it."
                ),
            )
        return RendererAvailability(available=True, renderer=self.name, version=ffmpeg_path)

    async def render_clip(self, spec: ClipRenderSpec, storage: StoragePort) -> ClipRenderOutput:
        availability = self.availability()
        if not availability.available:
            raise RendererUnavailableError(availability.reason or "FFmpeg is unavailable.")

        with tempfile.TemporaryDirectory(prefix="olympus-render-") as tmp:
            tmp_dir = Path(tmp)
            source_path = await self._materialize_source(spec.source_key, storage, tmp_dir)
            timeline = self._timeline_with_assets(spec.timeline, spec.output_key)
            caption_path, caption_context = self._write_ass(timeline, tmp_dir)
            output_path = tmp_dir / "out.mp4"

            args = C.build_ffmpeg_command(
                binary=self._ffmpeg,
                source_path=str(source_path),
                output_path=str(output_path),
                timeline=timeline,
                width=spec.width,
                height=spec.height,
                fps=spec.fps,
                video_bitrate_kbps=spec.video_bitrate_kbps,
                audio_bitrate_kbps=spec.audio_bitrate_kbps,
                srt_path=str(caption_path) if caption_path else None,
            )
            filtergraph = ""
            if "-filter_complex" in args:
                graph_index = args.index("-filter_complex") + 1
                if graph_index < len(args):
                    filtergraph = args[graph_index]
            logs = await self._run(args, label="ffmpeg")
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise ExternalServiceError(
                    "FFmpeg completed but produced no output file.",
                    code="render_failed",
                    details={"clip_id": spec.clip_id},
                )

            data = await asyncio.to_thread(output_path.read_bytes)
            caption_context["ffmpeg_filter_present"] = caption_path is not None
            caption_context["output_exists"] = True
            render_context = {
                "ffmpeg_filtergraph": filtergraph,
                "expected_motion_filters": C.motion_expected_filters(timeline),
                "output_exists": True,
            }
            self._record_music_use(timeline, spec.output_key)
            await storage.put(spec.output_key, data, content_type="video/mp4")
            probe = await self._probe(output_path)
            return self._build_output(
                spec,
                data,
                probe,
                logs,
                timeline,
                caption_context,
                render_context,
            )

    # -- internals ------------------------------------------------------------
    async def _materialize_source(
        self, source_key: str, storage: StoragePort, tmp_dir: Path
    ) -> Path:
        local = storage.local_path(source_key)
        if local is not None and Path(local).exists():
            return Path(local)
        if not await storage.exists(source_key):
            raise ExternalServiceError(
                "Source media is missing from storage; cannot render.",
                code="missing_source",
                details={"source_key": source_key},
            )
        data = await storage.get(source_key)
        dest = tmp_dir / "source"
        await asyncio.to_thread(dest.write_bytes, data)
        return dest

    @staticmethod
    def _music_scope(output_key: str) -> str:
        parts = output_key.replace("\\", "/").split("/")
        project_id = parts[1] if len(parts) > 1 and parts[0] == "render" else "unknown"
        phase = "preview" if "preview_" in output_key else "full"
        return f"{project_id}:{phase}"

    def _timeline_with_assets(
        self, timeline: dict[str, Any], output_key: str = ""
    ) -> dict[str, Any]:
        resolved = copy.deepcopy(timeline)
        metadata = resolved.setdefault("metadata", {})
        if isinstance(metadata, dict):
            scope = self._music_scope(output_key)
            metadata["render_assets_v2"] = resolve_assets(
                resolved,
                self._asset_root,
                music_usage_counts=self._music_usage_counts.setdefault(scope, {}),
            )
        return resolved

    def _record_music_use(self, timeline: dict[str, Any], output_key: str) -> None:
        assets = _dict_value(_dict_value(timeline, "metadata"), "render_assets_v2")
        music = _dict_value(assets, "music")
        asset_id = str(music.get("asset_id") or "")
        if not asset_id or not music.get("mixed"):
            return
        counts = self._music_usage_counts.setdefault(self._music_scope(output_key), {})
        counts[asset_id] = counts.get(asset_id, 0) + 1

    def _write_ass(
        self, timeline: dict[str, Any], tmp_dir: Path
    ) -> tuple[Path | None, dict[str, Any]]:
        cues = C.caption_cues(timeline)
        if not cues:
            return None, {
                "captions_planned": False,
                "ass_file_created": False,
                "ass_file_exists": False,
                "ass_non_empty": False,
                "ass_valid": None,
                "ass_event_count": 0,
                "ass_styles_count": 0,
                "ffmpeg_filter_present": False,
                "output_exists": False,
                "warnings": [],
            }
        content = C.build_ass(cues, timeline)
        validation = C.validate_ass(content)
        ass_path = tmp_dir / "captions.ass"
        ass_path.write_text(content, encoding="utf-8")
        return ass_path, {
            "captions_planned": True,
            "ass_file_created": True,
            "ass_file_exists": ass_path.exists(),
            "ass_non_empty": bool(content.strip()),
            "ass_valid": validation.get("ass_valid") is True,
            "ass_event_count": validation.get("events_count"),
            "ass_styles_count": validation.get("styles_count"),
            "ffmpeg_filter_present": False,
            "output_exists": False,
            "warnings": validation.get("warnings") or [],
        }

    async def _run(self, args: list[str], *, label: str) -> list[str]:
        log.info("render_exec", renderer=self.name, label=label, arg0=args[0])

        # Run via a blocking subprocess on a worker thread rather than
        # asyncio.create_subprocess_exec: the latter raises NotImplementedError on
        # event loops without subprocess support (e.g. a Windows
        # SelectorEventLoop). The threaded path works on every platform/loop.
        def _exec() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                list(args), capture_output=True, check=False, timeout=_RENDER_TIMEOUT_SECONDS
            )

        try:
            completed = await asyncio.to_thread(_exec)
        except subprocess.TimeoutExpired as exc:
            # subprocess.run has already killed the child here, so no FFmpeg
            # process is left running.
            raise ExternalServiceError(
                f"{label} timed out after {_RENDER_TIMEOUT_SECONDS:.0f}s and was terminated.",
                code="render_timeout",
                details={"timeout_seconds": _RENDER_TIMEOUT_SECONDS, "arg0": args[0]},
            ) from exc
        tail = (completed.stderr or b"").decode("utf-8", "replace").splitlines()[-_MAX_LOG_LINES:]
        if completed.returncode != 0:
            raise ExternalServiceError(
                f"{label} exited with code {completed.returncode}.",
                code="render_failed",
                details={"stderr_tail": tail[-5:]},
            )
        return [f"[{label}] {line}" for line in tail]

    async def _probe(self, path: Path) -> dict[str, Any]:
        if shutil.which(self._ffprobe) is None:
            return {}
        args = C.build_ffprobe_command(binary=self._ffprobe, path=str(path))

        def _exec() -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                list(args), capture_output=True, check=False, timeout=_PROBE_TIMEOUT_SECONDS
            )

        try:
            completed = await asyncio.to_thread(_exec)
        except subprocess.TimeoutExpired:
            log.warning("ffprobe_timeout", path=str(path), timeout_seconds=_PROBE_TIMEOUT_SECONDS)
            return {}
        if completed.returncode != 0:
            return {}
        try:
            parsed: Any = json.loads((completed.stdout or b"").decode("utf-8", "replace"))
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _build_output(
        spec: ClipRenderSpec,
        data: bytes,
        probe: dict[str, Any],
        logs: list[str],
        timeline: dict[str, Any],
        caption_context: dict[str, Any],
        render_context: dict[str, Any] | None = None,
    ) -> ClipRenderOutput:
        fmt = probe.get("format", {}) if isinstance(probe, dict) else {}
        streams = probe.get("streams", []) if isinstance(probe, dict) else []
        video: dict[str, Any] = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

        def _to_float(value: object) -> float | None:
            try:
                return float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None

        duration = _to_float(fmt.get("duration"))
        bitrate = _to_float(fmt.get("bit_rate"))
        metadata = _render_metadata(
            timeline,
            logs,
            probe,
            caption_context,
            render_context,
        )
        return ClipRenderOutput(
            clip_id=spec.clip_id,
            output_key=spec.output_key,
            width=video.get("width") or spec.width,
            height=video.get("height") or spec.height,
            duration=duration,
            fps=float(spec.fps),
            video_codec=video.get("codec_name") or "h264",
            audio_codec=(audio or {}).get("codec_name") if audio else None,
            has_audio=audio is not None,
            bitrate_kbps=int(bitrate / 1000) if bitrate else spec.video_bitrate_kbps,
            audio_sample_rate=int((audio or {}).get("sample_rate", 0)) or None if audio else None,
            size_bytes=len(data),
            logs=logs,
            metadata=metadata,
        )


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _dict_value(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    return value if isinstance(value, dict) else {}


def _duration_validation(
    timeline: dict[str, Any],
    format_duration: float | None,
) -> dict[str, Any]:
    expected = C.expected_duration(timeline)
    rendered = format_duration or 0.0
    delta = rendered - expected if rendered else None
    warnings: list[str] = []
    passed = delta is not None and abs(delta) <= 0.15
    if delta is None:
        warnings.append("ffprobe did not report a container duration.")
    elif not passed:
        warnings.append(f"Rendered duration differs from timeline by {abs(delta):.3f}s.")
    return {
        "planned_duration": round(expected, 3),
        "timeline_duration": round(expected, 3),
        "rendered_duration": round(rendered, 3) if rendered else None,
        "delta": round(delta, 3) if delta is not None else None,
        "passed": passed,
        "warnings": warnings,
    }


def _sync_validation(
    timeline: dict[str, Any],
    format_duration: float | None,
    video: dict[str, Any],
    audio: dict[str, Any] | None,
) -> dict[str, Any]:
    expected = C.expected_duration(timeline)
    container_duration = format_duration or 0.0
    video_duration = _to_float(video.get("duration")) or container_duration or None
    audio_duration = _to_float((audio or {}).get("duration")) or container_duration or None
    av_delta = (
        audio_duration - video_duration
        if audio_duration is not None and video_duration is not None
        else None
    )
    duration_delta = container_duration - expected if container_duration else None
    warnings: list[str] = []
    passed = True
    if av_delta is None:
        warnings.append("ffprobe did not report both audio and video durations.")
        passed = False
    elif abs(av_delta) > 0.15:
        warnings.append(f"Audio/video stream durations differ by {abs(av_delta):.3f}s.")
        passed = False
    if duration_delta is None:
        warnings.append("ffprobe did not report a container duration.")
        passed = False
    elif abs(duration_delta) > 0.15:
        warnings.append(f"Container duration differs from plan by {abs(duration_delta):.3f}s.")
        passed = False
    return {
        "expected_duration": round(expected, 3),
        "actual_container_duration": round(container_duration, 3) if container_duration else None,
        "actual_video_duration": round(video_duration, 3) if video_duration is not None else None,
        "actual_audio_duration": round(audio_duration, 3) if audio_duration is not None else None,
        "audio_video_delta": round(av_delta, 3) if av_delta is not None else None,
        "duration_delta": round(duration_delta, 3) if duration_delta is not None else None,
        "passed": passed,
        "warnings": warnings,
    }


def _render_metadata(
    timeline: dict[str, Any],
    logs: list[str],
    probe: dict[str, Any] | None = None,
    caption_context: dict[str, Any] | None = None,
    render_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = _dict_value(timeline, "metadata")
    probe = probe if isinstance(probe, dict) else {}
    fmt = _dict_value(probe, "format")
    streams = probe.get("streams", []) if isinstance(probe.get("streams"), list) else []
    probe_video: dict[str, Any] = next(
        (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"), {}
    )
    probe_audio = next(
        (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"), None
    )
    format_duration = _to_float(fmt.get("duration"))
    assets = _dict_value(meta, "render_assets_v2")
    editing = _dict_value(meta, "editing_v2")
    face_plan = _dict_value(meta, "face_tracking_plan")
    multi_speaker_plan = _dict_value(meta, "multi_speaker_layout_v2") or face_plan
    music = _dict_value(assets, "music")
    sfx = _dict_value(assets, "sfx")
    voice = _dict_value(editing, "voice_enhancement_plan")
    video = _dict_value(editing, "video_enhancement_plan")
    captions = _dict_value(editing, "caption_style")
    caption_intelligence = copy.deepcopy(
        _dict_value(meta, "caption_intelligence_v2")
        or _dict_value(editing, "caption_intelligence_v2")
    )
    caption_context = caption_context if isinstance(caption_context, dict) else {}
    render_context = render_context if isinstance(render_context, dict) else {}
    captions_planned = bool(C.caption_cues(timeline))
    caption_render_warnings = list(caption_context.get("warnings") or [])
    caption_rendered = bool(
        captions_planned
        and caption_context.get("ass_file_created") is True
        and caption_context.get("ass_file_exists") is True
        and caption_context.get("ass_non_empty") is True
        and caption_context.get("ass_valid") is True
        and caption_context.get("ffmpeg_filter_present") is True
        and caption_context.get("output_exists") is True
    )
    if captions_planned and not caption_rendered:
        caption_render_warnings.append(
            "Captions were planned but ASS creation/filter/output proof was incomplete."
        )
    caption_render_validation = {
        "captions_planned": captions_planned,
        "ass_file_exists": caption_context.get("ass_file_exists") is True,
        "ass_event_count": int(caption_context.get("ass_event_count") or 0),
        "ass_styles_count": int(caption_context.get("ass_styles_count") or 0),
        "ffmpeg_filter_present": caption_context.get("ffmpeg_filter_present") is True,
        "render_manifest_confirmed": False,
        "output_exists": caption_context.get("output_exists") is True,
        "frame_probe_performed": False,
        "frames_extracted": 0,
        "visual_presence_verified": False,
        "warnings": caption_render_warnings,
        "passed": caption_rendered if captions_planned else True,
    }
    if caption_intelligence:
        caption_render_plan = _dict_value(caption_intelligence, "render_plan")
        caption_render_plan["ass_path"] = (
            "temporary_renderer_file" if caption_context.get("ass_file_created") else None
        )
        caption_render_plan["events_count"] = caption_render_validation["ass_event_count"]
        caption_render_plan["styles_count"] = caption_render_validation["ass_styles_count"]
        caption_intelligence["render_plan"] = caption_render_plan
        ass_generation = _dict_value(caption_intelligence, "ass_generation")
        ass_generation["path"] = caption_render_plan["ass_path"]
        ass_generation["events_count"] = caption_render_validation["ass_event_count"]
        ass_generation["styles_count"] = caption_render_validation["ass_styles_count"]
        ass_generation["warnings"] = caption_render_warnings
        caption_intelligence["ass_generation"] = ass_generation
        caption_validation = _dict_value(caption_intelligence, "validation")
        caption_validation.update(
            {
                "captions_file_created": caption_context.get("ass_file_created") is True,
                "captions_rendered": caption_rendered,
                "ass_valid": caption_context.get("ass_valid"),
                "event_count": caption_render_validation["ass_event_count"],
                "render_manifest_confirmed": False,
                "warnings": list(
                    dict.fromkeys(
                        [
                            *list(caption_validation.get("warnings") or []),
                            *caption_render_warnings,
                        ]
                    )
                ),
                "passed": bool(
                    caption_render_validation["passed"]
                    and _dict_value(
                        caption_intelligence, "caption_readability_validation"
                    ).get("passed", True)
                ),
            }
        )
        caption_intelligence["validation"] = caption_validation
    motion = _dict_value(editing, "motion_plan")
    motion_intelligence = copy.deepcopy(C.motion_intelligence(timeline))
    face_applied = C.face_tracking_renderable(timeline)
    sync = _sync_validation(timeline, format_duration, probe_video, probe_audio)
    duration = _duration_validation(timeline, format_duration)
    motion_effects = C.motion_effects(timeline)
    expected_motion_filters = C.motion_expected_filters(timeline)
    filtergraph = str(render_context.get("ffmpeg_filtergraph") or "")
    found_motion_filters = [
        expected for expected in expected_motion_filters if expected in filtergraph
    ]
    motion_filters_present = bool(
        expected_motion_filters
        and len(found_motion_filters) == len(expected_motion_filters)
    )
    motion_output_exists = render_context.get("output_exists") is True
    motion_probe_passed = bool(probe_video and format_duration)
    motion_safety = _dict_value(motion_intelligence, "motion_safety_validation")
    motion_decision = _dict_value(motion_intelligence, "decision")
    planned_motion_count = len(motion_effects)
    rendered_motion_count = (
        planned_motion_count
        if planned_motion_count
        and motion_filters_present
        and motion_output_exists
        and motion_probe_passed
        else 0
    )
    motion_warnings = list(_dict_value(motion_intelligence, "effect_plan").get("warnings") or [])
    if planned_motion_count and not motion_filters_present:
        motion_warnings.append("Expected Motion V2 filters were missing from the FFmpeg graph.")
    if planned_motion_count and not motion_output_exists:
        motion_warnings.append("Motion was planned but no rendered output was confirmed.")
    if planned_motion_count and not motion_probe_passed:
        motion_warnings.append("Motion was planned but ffprobe did not confirm the video output.")
    if planned_motion_count and sync.get("passed") is not True:
        motion_warnings.append("Motion render failed audio/video sync validation.")
    if planned_motion_count and duration.get("passed") is not True:
        motion_warnings.append("Motion render failed duration validation.")
    motion_render_passed = bool(
        (
            not planned_motion_count
            and motion_decision.get("should_apply_motion") is not True
        )
        or (
            rendered_motion_count == planned_motion_count
            and motion_safety.get("passed") is True
            and sync.get("passed") is True
            and duration.get("passed") is True
        )
    )
    motion_render_validation = {
        "effects_planned": planned_motion_count,
        "effects_rendered": rendered_motion_count,
        "expected_filters": expected_motion_filters,
        "expected_filters_found": found_motion_filters,
        "ffmpeg_filter_present": motion_filters_present if planned_motion_count else False,
        "rendered_file_exists": motion_output_exists,
        "output_exists": motion_output_exists,
        "ffprobe_passed": motion_probe_passed,
        "sync_passed": sync.get("passed") is True,
        "duration_passed": duration.get("passed") is True,
        "safety_passed": motion_safety.get("passed") is True,
        "frames_extracted": 0,
        "visual_probe_performed": False,
        "render_manifest_confirmed": False,
        "passed": motion_render_passed,
        "warnings": list(dict.fromkeys(motion_warnings)),
    }
    if motion_intelligence:
        motion_intelligence["validation"] = copy.deepcopy(motion_render_validation)
    layout_mode = str(multi_speaker_plan.get("mode") or "center_fallback")
    layout_regions = multi_speaker_plan.get("layout_regions")
    layout_regions = layout_regions if isinstance(layout_regions, list) else []
    layout_switches = multi_speaker_plan.get("speaker_switches")
    layout_switches = layout_switches if isinstance(layout_switches, list) else []
    layout_render_plan = _dict_value(multi_speaker_plan, "render_plan")
    expected_layout_width = _to_float(layout_render_plan.get("output_width")) or 1080.0
    expected_layout_height = _to_float(layout_render_plan.get("output_height")) or 1920.0
    dimensions_passed = (
        _to_float(probe_video.get("width")) == expected_layout_width
        and _to_float(probe_video.get("height")) == expected_layout_height
    )
    rendered_regions = 2 if face_applied and layout_mode == "two_speaker_stack" else int(
        face_applied
    )
    rendered_switches = (
        len(layout_switches)
        if face_applied and layout_mode == "active_speaker_focus"
        else 0
    )
    layout_warnings = list(multi_speaker_plan.get("warnings") or [])
    if layout_mode == "center_fallback":
        truth_matches = not face_applied
    elif layout_mode == "two_speaker_stack":
        truth_matches = face_applied and len(layout_regions) >= 2 and rendered_regions == 2
    elif layout_mode == "active_speaker_focus":
        truth_matches = (
            face_applied
            and len(layout_switches) >= 1
            and rendered_switches == len(layout_switches)
        )
    else:
        truth_matches = face_applied
    if not truth_matches:
        layout_warnings.append("Planned layout mode did not match the rendered filter path.")
    if not dimensions_passed:
        layout_warnings.append("Rendered dimensions did not match the layout render plan.")
    multi_speaker_validation = {
        "planned_mode": layout_mode,
        "applied": face_applied,
        "applied_mode": layout_mode if face_applied else "center_fallback",
        "expected_regions": len(layout_regions)
        if layout_mode == "two_speaker_stack"
        else int(layout_mode != "center_fallback"),
        "rendered_regions": rendered_regions,
        "expected_switches": len(layout_switches),
        "rendered_switches": rendered_switches,
        "face_tracks_used": len(multi_speaker_plan.get("participants") or []),
        "speaker_associations_used": len(
            [
                item
                for item in multi_speaker_plan.get("speaker_face_associations") or []
                if isinstance(item, dict) and item.get("face_track_id")
            ]
        ),
        "output_width": probe_video.get("width"),
        "output_height": probe_video.get("height"),
        "dimensions_passed": dimensions_passed,
        "expected_duration": C.expected_duration(timeline),
        "rendered_duration": format_duration,
        "audio_video_delta": sync.get("audio_video_delta"),
        "sync_passed": sync.get("passed") is True,
        "duration_passed": duration.get("passed") is True,
        "fallback_reason": multi_speaker_plan.get("fallback_reason"),
        "warnings": layout_warnings,
        "passed": bool(
            truth_matches and dimensions_passed and sync.get("passed") and duration.get("passed")
        ),
    }
    rendered_multi_speaker_plan = copy.deepcopy(multi_speaker_plan)
    if rendered_multi_speaker_plan:
        rendered_multi_speaker_plan["applied_to_render"] = face_applied
        rendered_multi_speaker_plan["validation"] = {
            "applied": face_applied,
            "applied_mode": multi_speaker_validation["applied_mode"],
            "rendered_regions": rendered_regions,
            "rendered_switches": rendered_switches,
            "sync_passed": multi_speaker_validation["sync_passed"],
            "duration_passed": multi_speaker_validation["duration_passed"],
            "warnings": layout_warnings,
        }
    music_intelligence = _dict_value(music, "music_intelligence_v2") or _dict_value(
        meta, "music_intelligence_v2"
    )
    if not music_intelligence and music.get("mixed") and music.get("path"):
        legacy_license = _dict_value(music, "license")
        music_intelligence = {
            "music_decision_id": "legacy_render_asset",
            "decision": {
                "should_use_music": True,
                "reason": music.get("reason") or "Legacy render asset was mixed.",
                "music_role": music.get("role") or "subtle_bed",
                "target_mood": music.get("mood"),
            },
            "selected_asset": {
                "path": music.get("path"),
                "asset_id": music.get("asset_id"),
                "title": music.get("title") or music.get("filename"),
                "license": legacy_license.get("license"),
                "license_verified": legacy_license.get("license_verified") is True,
                "safe_default": legacy_license.get("safe_default") is True,
            },
            "mix_plan": music.get("mix_plan")
            or {"music_gain_db": music.get("gain_db")},
            "validation": {},
        }
    music_validation = build_music_validation(
        music_intelligence,
        output_audio_present=probe_audio is not None,
        sync_validation=sync,
        duration_validation=duration,
        ffmpeg_completed=True,
    )
    if music_intelligence:
        music_intelligence = copy.deepcopy(music_intelligence)
        music_intelligence["validation"] = {
            "music_mixed": music_validation.get("mixed"),
            "music_audible": music_validation.get("audible"),
            "speech_clarity_passed": music_validation.get("speech_clarity_passed"),
            "audio_video_sync_passed": music_validation.get("audio_video_sync_passed"),
            "duration_passed": music_validation.get("duration_passed"),
            "loudness_summary": music_validation.get("loudness_estimate"),
            "warnings": music_validation.get("warnings") or [],
        }
    music_mixed = bool(music_validation.get("mixed"))
    metadata = {
        "editing_v2": editing,
        "render_effects_v2": {
            "captions": {
                "included": caption_rendered,
                "style": captions.get("style"),
                "renderer": "ass",
                "timing_source": _dict_value(
                    caption_intelligence, "caption_timing_quality"
                ).get("source"),
                "hook_treatment": _dict_value(
                    caption_intelligence, "hook_caption_treatment"
                ).get("applied"),
                "highlighted_words_count": len(
                    _dict_value(caption_intelligence, "caption_emphasis").get(
                        "highlighted_words", []
                    )
                ),
                "speaker_aware": _dict_value(
                    caption_intelligence, "speaker_captioning"
                ).get("enabled"),
                "safe_zone_strategy": _dict_value(
                    caption_intelligence, "caption_safe_zone"
                ).get("strategy"),
                "validation": caption_render_validation,
            },
            "music": music,
            "sfx": sfx,
            "face_tracking": {
                "applied": face_applied,
                "mode": face_plan.get("mode") or "center_fallback",
                "keyframes_count": len(C.face_tracking_plan(timeline).get("crop_keyframes") or []),
                "fallback_reason": face_plan.get("fallback_reason"),
                "confidence": face_plan.get("confidence"),
                "warnings": face_plan.get("warnings") or [],
            },
            "multi_speaker_layout": {
                "applied": face_applied,
                "mode": layout_mode,
                "rendered_regions": rendered_regions,
                "rendered_switches": rendered_switches,
                "validation": multi_speaker_validation,
            },
            "voice_enhancement": {
                "applied": True,
                "filters": voice.get("filters"),
                "target": voice.get("loudness_target"),
            },
            "video_enhancement": {
                "applied": True,
                "profile": video.get("profile"),
                "filters": video.get("filters"),
            },
            "motion": {
                "applied": rendered_motion_count > 0 and motion_render_passed,
                "motion_style": motion_decision.get("motion_style"),
                "intensity": motion_decision.get("intensity"),
                "event_count": rendered_motion_count,
                "planned_event_count": planned_motion_count,
                "events": motion_effects or motion.get("events", []),
                "hook_effect": _dict_value(motion_intelligence, "hook_motion_treatment"),
                "payoff_effect": _dict_value(
                    motion_intelligence, "payoff_motion_treatment"
                ),
                "safety_validation": motion_safety,
                "render_validation": motion_render_validation,
            },
            "logs_tail": logs[-8:],
        },
        "face_tracking": {
            "applied": face_applied,
            "mode": face_plan.get("mode") or "center_fallback",
            "keyframes_count": len(C.face_tracking_plan(timeline).get("crop_keyframes") or []),
            "fallback_reason": face_plan.get("fallback_reason"),
            "confidence": face_plan.get("confidence"),
            "warnings": face_plan.get("warnings") or [],
        },
        "face_tracking_applied": face_applied,
        "multi_speaker_layout_v2": rendered_multi_speaker_plan,
        "multi_speaker_validation": multi_speaker_validation,
        "caption_intelligence_v2": caption_intelligence,
        "caption_readability_validation": _dict_value(
            caption_intelligence, "caption_readability_validation"
        ),
        "caption_render_validation": caption_render_validation,
        "motion_intelligence_v2": motion_intelligence,
        "motion_safety_validation": motion_safety,
        "motion_render_validation": motion_render_validation,
        "music_mixed": music_mixed,
        "music_asset": music.get("filename") or music.get("asset_id"),
        "music_gain_db": music.get("gain_db"),
        "music_looped": bool(music.get("looped")),
        "music_duration_used": music.get("duration_used"),
        "music_fade_in": music.get("fade_in_s"),
        "music_fade_out": music.get("fade_out_s"),
        "music_license": music.get("license"),
        "music_reason": music.get("reason"),
        "music_warning": music_validation.get("warning")
        or (None if music_mixed else music.get("reason")),
        "music_validation": music_validation,
        "music_intelligence_v2": music_intelligence,
        "sfx_mixed_count": int(sfx.get("mixed_count") or 0),
        "sfx_planned_count": int(sfx.get("planned_count") or 0),
        "sfx_skipped_count": int(sfx.get("skipped_count") or 0),
        "sfx_skipped_reasons": sfx.get("skipped_reasons") or [],
        "sfx_safety_applied": bool(sfx.get("safety_applied")),
        "sync_validation": sync,
        "duration_validation": duration,
        "hook_editing": _dict_value(editing, "hook_editing"),
        "personalization_applied_v2": _dict_value(
            editing, "personalization_applied_v2"
        ),
        "voice_enhancement_applied": True,
        "video_enhancement_applied": True,
    }
    metadata["unified_clip_intelligence"] = CI.unified_clip_intelligence(
        clip=timeline,
        editing_v2=editing,
        render_metadata={
            **metadata,
            "unified_clip_intelligence": meta.get("unified_clip_intelligence"),
        },
    )
    return metadata


def build_clip_renderer(ffmpeg_binary: str = "ffmpeg") -> ClipRenderer:
    """Construct the default clip renderer (FFmpeg).

    The Rendering Engine depends only on the :class:`ClipRenderer` abstraction, so
    a future deployment can swap this for a GPU/cloud/distributed renderer here
    without touching any pipeline stage.
    """

    from olympus.platform.config import get_settings

    settings = get_settings()
    return FfmpegClipRenderer(
        ffmpeg_binary=ffmpeg_binary,
        asset_root=settings.rendering.asset_root,
    )
