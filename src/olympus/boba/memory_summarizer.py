"""Small deterministic helpers for bounded BOBA memory summaries."""

from __future__ import annotations

from typing import Any

from olympus.boba.memory import compact_strings
from olympus.boba.memory_validation import truncate_safe_excerpt


def memory_strings(values: Any, *, limit: int = 24, max_chars: int = 240) -> list[str]:
    return compact_strings(values, limit=limit, max_chars=max_chars)


def memory_summary(parts: list[Any], *, max_chars: int = 600) -> str:
    text = ". ".join(str(part).strip().rstrip(".") for part in parts if str(part).strip())
    return truncate_safe_excerpt(text, max_chars=max_chars)


def safe_excerpt(value: Any, *, max_chars: int = 300) -> str:
    return truncate_safe_excerpt(str(value or ""), max_chars=max_chars)


def safe_range(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    start_value = value.get("start", value.get("source_start", 0.0))
    if start_value is None:
        return None
    try:
        start = float(start_value)
        end_value = value.get("end", value.get("source_end", start))
        if end_value is None:
            return None
        end = float(end_value)
    except (TypeError, ValueError):
        return None
    if start < 0 or end <= start:
        return None
    return {"start": round(start, 3), "end": round(end, 3)}
