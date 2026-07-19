"""Honest speaker-label and speech-turn fallback segmentation."""

from __future__ import annotations

from typing import Any

from olympus.analysis.signals import (
    AnalysisSignalState,
    AnalysisSignalStatusV1,
    AnalysisTimelineEventV1,
    AnalysisTimelineSignalV1,
)


def build_speaker_segmentation(
    transcript_segments: list[dict[str, Any]] | None,
    *,
    silence_events: list[dict[str, Any]] | None = None,
    duration_seconds: float | None = None,
) -> dict[str, Any] | None:
    segments = [item for item in transcript_segments or [] if isinstance(item, dict)]
    if segments and any(item.get("speaker") for item in segments):
        timeline = _from_labels(segments)
        return _result(
            timeline,
            state=AnalysisSignalState.AVAILABLE,
            provider="transcript_speaker_labels",
            confidence=0.82,
            diarization=True,
            warnings=[],
        )
    if segments:
        timeline = _turns_from_segments(segments)
        return _result(
            timeline,
            state=AnalysisSignalState.FALLBACK,
            provider="transcript_gap_turns",
            confidence=0.42,
            diarization=False,
            warnings=[
                "Turn labels are inferred from transcript gaps and do not identify "
                "distinct speakers."
            ],
        )
    timeline = _turns_from_silence(
        silence_events or [],
        duration_seconds=duration_seconds,
    )
    if timeline:
        return _result(
            timeline,
            state=AnalysisSignalState.FALLBACK,
            provider="audio_silence_turns",
            confidence=0.3,
            diarization=False,
            warnings=[
                "Turn regions are inferred from silence gaps; true speaker diarization "
                "is unavailable."
            ],
        )
    return None


def _from_labels(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    for segment in segments:
        speaker = str(segment.get("speaker") or "unknown")
        start = _float(segment.get("start"))
        end = max(start, _float(segment.get("end"), start))
        if timeline and timeline[-1]["speaker"] == speaker and start <= timeline[-1]["end"] + 0.35:
            timeline[-1]["end"] = end
        else:
            timeline.append({"speaker": speaker, "start": start, "end": end})
    return timeline


def _turns_from_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timeline: list[dict[str, Any]] = []
    turn_number = 1
    for segment in segments:
        start = _float(segment.get("start"))
        end = max(start, _float(segment.get("end"), start))
        if timeline and start - float(timeline[-1]["end"]) < 0.65:
            timeline[-1]["end"] = end
            continue
        timeline.append({"speaker": f"turn_{turn_number}", "start": start, "end": end})
        turn_number += 1
    return timeline


def _turns_from_silence(
    events: list[dict[str, Any]],
    *,
    duration_seconds: float | None,
) -> list[dict[str, Any]]:
    silence = sorted(
        (
            (
                _float(item.get("start_seconds") or item.get("start")),
                _float(item.get("end_seconds") or item.get("end")),
            )
            for item in events
            if isinstance(item, dict)
        ),
        key=lambda item: item[0],
    )
    if not silence:
        return []
    timeline: list[dict[str, Any]] = []
    cursor = 0.0
    turn_number = 1
    for start, end in silence:
        if start > cursor + 0.2:
            timeline.append({"speaker": f"turn_{turn_number}", "start": cursor, "end": start})
            turn_number += 1
        cursor = max(cursor, end)
    duration = max(0.0, float(duration_seconds or 0.0))
    if duration > cursor + 0.2:
        timeline.append({"speaker": f"turn_{turn_number}", "start": cursor, "end": duration})
    return timeline


def _result(
    timeline: list[dict[str, Any]],
    *,
    state: AnalysisSignalState,
    provider: str,
    confidence: float,
    diarization: bool,
    warnings: list[str],
) -> dict[str, Any]:
    events = [
        AnalysisTimelineEventV1(
            start_seconds=float(item["start"]),
            end_seconds=float(item["end"]),
            label=str(item["speaker"]),
            score=confidence,
            metadata={"diarized": diarization},
        )
        for item in timeline
    ]
    status = AnalysisSignalStatusV1(
        signal_name="speaker_segmentation",
        available=bool(timeline),
        status=state,
        confidence=confidence,
        provider=provider,
        fallback_used=state is AnalysisSignalState.FALLBACK,
        reason=None,
        warnings=warnings,
        metadata={"true_diarization": diarization, "turn_count": len(timeline)},
    )
    return {
        "speakers": sorted({str(item["speaker"]) for item in timeline}),
        "timeline": timeline,
        "diarization_available": diarization,
        "speaker_segmentation": {
            "status": status.to_dict(),
            "timeline": AnalysisTimelineSignalV1(
                signal_name="speaker_segmentation",
                events=events,
                confidence=confidence,
                warnings=warnings,
            ).to_dict(),
        },
    }


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
