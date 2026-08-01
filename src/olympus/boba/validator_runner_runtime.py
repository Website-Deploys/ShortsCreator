"""Bounded subprocess adapters for the BOBA Validator Runner V1."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from olympus.boba.output_quality_reviewer import (
    build_read_only_quality_validator_registry,
    execute_read_only_quality_command,
    validate_quality_command_safety,
)
from olympus.boba.validator_runner import (
    BobaValidationCheckStatusV1,
    BobaValidationEvidenceSourceTypeV1,
    BobaValidationInputBindingV1,
    BobaValidationPlanCheckV1,
    _AdapterOutcome,
    _float_value,
    _int_value,
    _mapping,
)
from olympus.boba.validator_runner import (
    BobaValidatorRunnerV1 as _BobaValidatorRunnerBaseV1,
)
from olympus.platform.errors import ValidationError
from olympus.rendering.command import build_ffprobe_command
from olympus.validation.real_video import parse_probe

_MEDIA_SUFFIXES = frozenset({".m4v", ".mkv", ".mov", ".mp4", ".webm"})


class BobaValidatorRunnerV1(_BobaValidatorRunnerBaseV1):
    """Complete Validator Runner with fixed media and isolated-code adapters."""

    def _execute_media_adapter(
        self,
        check: BobaValidationPlanCheckV1,
        bindings: Sequence[BobaValidationInputBindingV1],
        workspace: Path,
    ) -> _AdapterOutcome:
        media_paths = [
            path
            for item in bindings
            if item.available
            for path in [self._resolve_binding_target(item)]
            if path.is_file() and path.suffix.casefold() in _MEDIA_SUFFIXES
        ]
        if len(media_paths) != 1:
            raise ValidationError(
                "Media validation requires one exact local media file."
            )
        media_path = media_paths[0]
        registry = build_read_only_quality_validator_registry(
            ffprobe_binary=self.ffprobe_binary,
            ffmpeg_binary=self.ffmpeg_binary,
        )
        if check.validator_id == "media.decode_to_null":
            return self._execute_media_decode(
                check,
                media_path=media_path,
                workspace=workspace,
                registry=registry,
            )
        validator = registry["ffprobe_media"]
        if not validator.available or validator.executable is None:
            return self._unavailable_process_outcome(
                tool_name="FFprobe",
                source_type="ffprobe",
            )
        command = build_ffprobe_command(
            binary=validator.executable,
            path=str(media_path),
        )
        command[4] = (
            "format=duration,start_time,bit_rate,size,format_name:"
            "stream=index,codec_type,codec_name,width,height,sample_rate,channels,"
            "avg_frame_rate,r_frame_rate,nb_frames,duration,start_time"
        )
        safety_errors = validate_quality_command_safety(
            validator_id="ffprobe_media",
            command=command,
            registry=registry,
            reviewed_path=media_path,
            working_directory=workspace,
        )
        if safety_errors:
            raise ValidationError(
                "The fixed FFprobe command failed safety validation.",
                details={"errors": safety_errors},
            )
        completed = execute_read_only_quality_command(
            validator_id="ffprobe_media",
            command=command,
            registry=registry,
            reviewed_path=media_path,
            working_directory=workspace,
        )
        if completed.timed_out:
            return _AdapterOutcome(
                status="timed_out",
                summary="The bounded FFprobe inspection timed out.",
                assertion_results={"ffprobe_completed": False},
                measured_values={"duration_seconds": completed.duration_seconds},
                expected_values={"ffprobe_completed": True},
                failed_assertions=["ffprobe_completed"],
                unavailable_assertions=[],
                source_type="ffprobe",
                confidence=1.0,
                stderr=completed.stderr,
                output_truncated=completed.output_truncated,
            )
        if completed.exit_code != 0:
            return _AdapterOutcome(
                status="failed",
                summary="FFprobe rejected the exact media input.",
                assertion_results={"ffprobe_exit_zero": False},
                measured_values={"exit_code": completed.exit_code},
                expected_values={"exit_code": 0},
                failed_assertions=["ffprobe_exit_zero"],
                unavailable_assertions=[],
                source_type="ffprobe",
                confidence=1.0,
                stdout=completed.stdout,
                stderr=completed.stderr,
                output_truncated=completed.output_truncated,
                exit_code=completed.exit_code,
            )
        try:
            raw_probe = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return _AdapterOutcome(
                status="errored",
                summary="FFprobe returned malformed JSON evidence.",
                assertion_results={"ffprobe_json_valid": False},
                measured_values={"stdout_length": len(completed.stdout)},
                expected_values={"ffprobe_json_valid": True},
                failed_assertions=["ffprobe_json_valid"],
                unavailable_assertions=[],
                source_type="ffprobe",
                confidence=1.0,
                stdout=completed.stdout,
                stderr=completed.stderr,
                output_truncated=completed.output_truncated,
                exit_code=completed.exit_code,
            )
        outcome = self._evaluate_media_probe(check, parse_probe(_mapping(raw_probe)))
        outcome.stdout = completed.stdout
        outcome.stderr = completed.stderr
        outcome.output_truncated = completed.output_truncated
        outcome.exit_code = completed.exit_code
        return outcome

    def _execute_media_decode(
        self,
        check: BobaValidationPlanCheckV1,
        *,
        media_path: Path,
        workspace: Path,
        registry: Mapping[str, Any],
    ) -> _AdapterOutcome:
        validator = registry["ffmpeg_decode"]
        if not validator.available or validator.executable is None:
            return self._unavailable_process_outcome(
                tool_name="FFmpeg",
                source_type="ffmpeg_decode",
            )
        expected_duration = _float_value(
            check.expected_values.get("duration_seconds"),
            30.0,
        )
        sample_duration = min(30.0, max(0.1, expected_duration or 30.0))
        command = [
            validator.executable,
            "-v",
            "error",
            "-nostdin",
            "-xerror",
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-t",
            f"{sample_duration:.3f}",
            "-i",
            str(media_path),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-f",
            "null",
            os.devnull,
        ]
        safety_errors = validate_quality_command_safety(
            validator_id="ffmpeg_decode",
            command=command,
            registry=registry,
            reviewed_path=media_path,
            working_directory=workspace,
        )
        if safety_errors:
            raise ValidationError(
                "The fixed FFmpeg decode command failed safety validation.",
                details={"errors": safety_errors},
            )
        completed = execute_read_only_quality_command(
            validator_id="ffmpeg_decode",
            command=command,
            registry=registry,
            reviewed_path=media_path,
            working_directory=workspace,
        )
        status: BobaValidationCheckStatusV1 = (
            "timed_out"
            if completed.timed_out
            else "passed"
            if completed.exit_code == 0
            else "failed"
        )
        return _AdapterOutcome(
            status=status,
            summary=(
                "Bounded FFmpeg decode completed without errors."
                if status == "passed"
                else "Bounded FFmpeg decode did not complete successfully."
            ),
            assertion_results={"bounded_decode_passed": status == "passed"},
            measured_values={
                "exit_code": completed.exit_code,
                "duration_seconds": completed.duration_seconds,
                "sample_duration_seconds": sample_duration,
            },
            expected_values={"exit_code": 0},
            failed_assertions=(
                [] if status == "passed" else ["bounded_decode_passed"]
            ),
            unavailable_assertions=[],
            source_type="ffmpeg_decode",
            confidence=1.0,
            stdout=completed.stdout,
            stderr=completed.stderr,
            output_truncated=completed.output_truncated,
            exit_code=completed.exit_code,
            limitations=["Decode validation is bounded to at most 30 seconds in V1."],
        )

    @staticmethod
    def _unavailable_process_outcome(
        *,
        tool_name: str,
        source_type: BobaValidationEvidenceSourceTypeV1,
    ) -> _AdapterOutcome:
        assertion = f"{tool_name.casefold()}_available"
        return _AdapterOutcome(
            status="unavailable",
            summary=f"The registered {tool_name} validator is unavailable.",
            assertion_results={assertion: None},
            measured_values={assertion: False},
            expected_values={assertion: True},
            failed_assertions=[],
            unavailable_assertions=[assertion],
            source_type=source_type,
            confidence=1.0,
        )

    def _evaluate_media_probe(
        self,
        check: BobaValidationPlanCheckV1,
        probe: Mapping[str, Any],
    ) -> _AdapterOutcome:
        expected = check.expected_values
        tolerance_seconds = float(check.tolerance.get("seconds", 0.15))
        tolerance_fps = float(check.tolerance.get("fps", 0.05))
        validator_id = check.validator_id
        assertions: dict[str, bool | None] = {"ffprobe_parsed": bool(probe)}
        expected_values: dict[str, Any] = {}
        if validator_id in {
            "media.ffprobe",
            "media.streams",
            "rendering.output_integrity",
            "recovery.output_integrity",
        }:
            assertions["video_stream_present"] = bool(probe.get("video_codec"))
            assertions["stream_count_positive"] = int(
                _int_value(probe.get("stream_count"), 0) or 0
            ) > 0
            expected_values.update(
                {"video_stream_present": True, "stream_count_minimum": 1}
            )
        if validator_id in {
            "media.duration",
            "media.source_window",
            "rendering.output_integrity",
            "recovery.output_integrity",
        }:
            expected_duration = _float_value(
                expected.get("duration_seconds")
                or expected.get("expected_duration_seconds")
            )
            if expected_duration is None:
                source_start = _float_value(expected.get("source_start_seconds"))
                source_end = _float_value(expected.get("source_end_seconds"))
                if (
                    source_start is not None
                    and source_end is not None
                    and source_end >= source_start
                ):
                    expected_duration = source_end - source_start
            actual_duration = _float_value(probe.get("container_duration"))
            assertions["duration_present"] = bool(
                actual_duration is not None and actual_duration > 0
            )
            assertions["duration_matches"] = (
                None
                if expected_duration is None or actual_duration is None
                else abs(actual_duration - expected_duration) <= tolerance_seconds
            )
            expected_values.update(
                {
                    "duration_seconds": expected_duration,
                    "duration_tolerance_seconds": tolerance_seconds,
                }
            )
        if validator_id in {
            "media.resolution",
            "rendering.output_integrity",
            "recovery.output_integrity",
        }:
            expected_width = _int_value(expected.get("width"))
            expected_height = _int_value(expected.get("height"))
            actual_width = _int_value(probe.get("width"))
            actual_height = _int_value(probe.get("height"))
            assertions["resolution_present"] = bool(actual_width and actual_height)
            assertions["width_matches"] = (
                None if expected_width is None else actual_width == expected_width
            )
            assertions["height_matches"] = (
                None if expected_height is None else actual_height == expected_height
            )
            expected_values.update(
                {"width": expected_width, "height": expected_height}
            )
        if validator_id in {
            "media.frame_rate",
            "rendering.output_integrity",
            "recovery.output_integrity",
        }:
            expected_fps = _float_value(
                expected.get("fps") or expected.get("frame_rate")
            )
            actual_fps = _float_value(probe.get("fps"))
            assertions["frame_rate_present"] = bool(
                actual_fps is not None and actual_fps > 0
            )
            assertions["frame_rate_matches"] = (
                None
                if expected_fps is None or actual_fps is None
                else abs(actual_fps - expected_fps) <= tolerance_fps
            )
            expected_values.update(
                {"fps": expected_fps, "fps_tolerance": tolerance_fps}
            )
        if validator_id in {
            "media.audio_presence",
            "media.av_sync",
            "rendering.output_integrity",
            "recovery.output_integrity",
        }:
            expected_audio = bool(expected.get("has_audio", True))
            assertions["audio_presence_matches"] = (
                bool(probe.get("has_audio")) == expected_audio
            )
            expected_values["has_audio"] = expected_audio
        if validator_id in {
            "media.av_sync",
            "rendering.output_integrity",
            "recovery.output_integrity",
        }:
            video_duration = _float_value(probe.get("video_duration"))
            audio_duration = _float_value(probe.get("audio_duration"))
            delta = (
                abs(video_duration - audio_duration)
                if video_duration is not None and audio_duration is not None
                else None
            )
            assertions["audio_video_delta_within_tolerance"] = (
                None if delta is None else delta <= tolerance_seconds
            )
            expected_values["maximum_audio_video_delta_seconds"] = tolerance_seconds
        failed = [key for key, value in assertions.items() if value is False]
        unavailable = [key for key, value in assertions.items() if value is None]
        status: BobaValidationCheckStatusV1 = (
            "failed" if failed else "unavailable" if unavailable else "passed"
        )
        return _AdapterOutcome(
            status=status,
            summary=(
                "FFprobe evidence satisfies every requested media assertion."
                if status == "passed"
                else "FFprobe evidence does not satisfy every requested media assertion."
            ),
            assertion_results=assertions,
            measured_values=dict(probe),
            expected_values=expected_values,
            failed_assertions=failed,
            unavailable_assertions=unavailable,
            source_type="ffprobe",
            confidence=1.0,
            limitations=[
                "FFprobe evidence is container and stream metadata, not manual playback."
            ],
        )

