"""Transparent transcript/audio heuristic for an emotion-like timeline."""

from __future__ import annotations

from typing import Any

from olympus.analysis.signals import (
    AnalysisSignalState,
    AnalysisSignalStatusV1,
    AnalysisTimelineEventV1,
    AnalysisTimelineSignalV1,
)

_LEXICONS: dict[str, set[str]] = {
    "positive": {"love", "great", "amazing", "win", "happy", "success", "best", "excited"},
    "tension": {"but", "problem", "risk", "hard", "wrong", "fail", "danger", "stuck"},
    "negative": {"hate", "sad", "angry", "loss", "hurt", "bad", "worse", "fear"},
    "surprise": {"suddenly", "actually", "secret", "reveal", "unexpected", "wow", "finally"},
}


def build_emotion_timeline(
    transcript_segments: list[dict[str, Any]],
    *,
    audio_energy_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    segments = [item for item in transcript_segments if isinstance(item, dict)]
    if not segments:
        return None
    events: list[dict[str, Any]] = []
    timeline_events: list[AnalysisTimelineEventV1] = []
    for segment in segments:
        text = str(segment.get("text") or "")
        words = {token.strip(".,!?;:\"'()[]{}").lower() for token in text.split()}
        matches = {label: len(words & lexicon) for label, lexicon in _LEXICONS.items()}
        label = max(matches, key=lambda name: matches[name]) if any(matches.values()) else "neutral"
        punctuation_boost = min(0.2, 0.05 * (text.count("!") + text.count("?")))
        energy = _overlapping_energy(
            _float(segment.get("start")),
            _float(segment.get("end")),
            audio_energy_events or [],
        )
        score = min(0.75, 0.3 + 0.12 * matches.get(label, 0) + punctuation_boost + 0.1 * energy)
        start = _float(segment.get("start"))
        end = max(start, _float(segment.get("end"), start))
        event = {
            "start": start,
            "end": end,
            "emotion": label,
            "label": label,
            "confidence": round(score, 3),
            "method": "transcript_audio_heuristic",
            "evidence": sorted(words & _LEXICONS.get(label, set()))[:6],
        }
        events.append(event)
        timeline_events.append(
            AnalysisTimelineEventV1(
                start_seconds=start,
                end_seconds=end,
                label=label,
                score=score,
                metadata={
                    "method": "transcript_audio_heuristic",
                    "keyword_matches": event["evidence"],
                    "audio_energy_contribution": round(energy, 3),
                },
            )
        )
    warnings = [
        "Emotion labels are a transcript/audio heuristic, not facial or psychological recognition."
    ]
    status = AnalysisSignalStatusV1(
        signal_name="emotion_timeline",
        available=True,
        status=AnalysisSignalState.FALLBACK,
        confidence=0.45,
        provider="transcript_audio_keyword_heuristic",
        fallback_used=True,
        reason=None,
        warnings=warnings,
        metadata={"model_used": False, "event_count": len(events)},
    )
    return {
        "timeline": events,
        "method": "transcript_audio_heuristic",
        "emotion_timeline": {
            "status": status.to_dict(),
            "timeline": AnalysisTimelineSignalV1(
                signal_name="emotion_timeline",
                events=timeline_events,
                confidence=status.confidence,
                warnings=warnings,
            ).to_dict(),
        },
    }


def _overlapping_energy(
    start: float,
    end: float,
    events: list[dict[str, Any]],
) -> float:
    scores = [
        _float(item.get("score"))
        for item in events
        if isinstance(item, dict)
        and _float(item.get("end_seconds") or item.get("end")) > start
        and _float(item.get("start_seconds") or item.get("start")) < end
    ]
    return sum(scores) / len(scores) if scores else 0.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
