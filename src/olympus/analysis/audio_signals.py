"""Deterministic local audio-energy and silence analysis."""

from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path
from typing import Any

from olympus.analysis.signals import (
    AnalysisSignalState,
    AnalysisSignalStatusV1,
    AnalysisTimelineEventV1,
    AnalysisTimelineSignalV1,
)


def analyze_wav_file(path: str | Path, *, window_seconds: float = 0.25) -> dict[str, Any]:
    with wave.open(str(path), "rb") as audio:
        sample_width = audio.getsampwidth()
        channels = audio.getnchannels()
        sample_rate = audio.getframerate()
        frames = audio.readframes(audio.getnframes())
    if sample_width != 2:
        raise ValueError(f"Expected 16-bit PCM WAV, received {sample_width * 8}-bit audio.")
    samples = array("h")
    samples.frombytes(frames)
    if channels > 1:
        samples = array("h", samples[::channels])
    normalized = [sample / 32768.0 for sample in samples]
    return analyze_pcm_samples(
        normalized,
        sample_rate=sample_rate,
        window_seconds=window_seconds,
    )


def analyze_pcm_samples(
    samples: list[float],
    *,
    sample_rate: int,
    window_seconds: float = 0.25,
    silence_db: float = -45.0,
    quiet_db: float = -30.0,
    loud_db: float = -14.0,
) -> dict[str, Any]:
    if sample_rate <= 0 or window_seconds <= 0:
        raise ValueError("sample_rate and window_seconds must be positive.")
    window_size = max(1, int(sample_rate * window_seconds))
    windows: list[dict[str, Any]] = []
    for offset in range(0, len(samples), window_size):
        chunk = samples[offset : offset + window_size]
        if not chunk:
            continue
        rms = math.sqrt(sum(sample * sample for sample in chunk) / len(chunk))
        dbfs = 20.0 * math.log10(max(rms, 1e-9))
        if dbfs <= silence_db:
            label = "silence"
        elif dbfs <= quiet_db:
            label = "quiet"
        elif dbfs >= loud_db:
            label = "loud"
        else:
            label = "normal"
        start = offset / sample_rate
        end = min(len(samples), offset + len(chunk)) / sample_rate
        windows.append(
            {
                "start": start,
                "end": end,
                "label": label,
                "dbfs": round(dbfs, 3),
                "score": round(max(0.0, min(1.0, (dbfs + 60.0) / 60.0)), 3),
            }
        )

    grouped = _group_windows(windows)
    energy_events = [
        AnalysisTimelineEventV1(
            start_seconds=item["start"],
            end_seconds=item["end"],
            label=item["label"],
            score=item["score"],
            metadata={"mean_dbfs": item["mean_dbfs"]},
        )
        for item in grouped
    ]
    silence_events = [
        AnalysisTimelineEventV1(
            start_seconds=item["start"],
            end_seconds=item["end"],
            label="silence",
            score=1.0,
            metadata={"mean_dbfs": item["mean_dbfs"]},
        )
        for item in grouped
        if item["label"] == "silence" and item["end"] - item["start"] >= 0.2
    ]
    confidence = 0.9 if windows else 0.0
    return {
        "audio_energy": _entry(
            "audio_energy",
            energy_events,
            confidence=confidence,
            source_available=bool(windows),
            metadata={"window_seconds": window_seconds, "sample_rate": sample_rate},
        ),
        "silence": _entry(
            "silence",
            silence_events,
            confidence=confidence,
            source_available=bool(windows),
            metadata={"threshold_dbfs": silence_db, "minimum_gap_seconds": 0.2},
        ),
    }


def _entry(
    signal_name: str,
    events: list[AnalysisTimelineEventV1],
    *,
    confidence: float,
    source_available: bool,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    status = AnalysisSignalStatusV1(
        signal_name=signal_name,
        available=source_available,
        status=(
            AnalysisSignalState.AVAILABLE
            if source_available
            else AnalysisSignalState.UNAVAILABLE
        ),
        confidence=confidence,
        provider="local_pcm_rms",
        fallback_used=False,
        reason=None if source_available else "insufficient_input",
        warnings=(
            [] if source_available else ["The decoded audio contained no measurable windows."]
        ),
        metadata=metadata,
    )
    timeline = AnalysisTimelineSignalV1(
        signal_name=signal_name,
        events=events,
        confidence=confidence,
        warnings=list(status.warnings),
    )
    return {"status": status.to_dict(), "timeline": timeline.to_dict()}


def _group_windows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    for window in windows:
        if grouped and grouped[-1]["label"] == window["label"]:
            current = grouped[-1]
            count = int(current["window_count"]) + 1
            current["end"] = window["end"]
            current["mean_dbfs"] = round(
                (float(current["mean_dbfs"]) * (count - 1) + float(window["dbfs"])) / count,
                3,
            )
            current["score"] = round(
                (float(current["score"]) * (count - 1) + float(window["score"])) / count,
                3,
            )
            current["window_count"] = count
            continue
        grouped.append(
            {
                "start": window["start"],
                "end": window["end"],
                "label": window["label"],
                "mean_dbfs": window["dbfs"],
                "score": window["score"],
                "window_count": 1,
            }
        )
    return grouped
