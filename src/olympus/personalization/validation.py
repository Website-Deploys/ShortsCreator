"""Privacy and payload validation for local personalization data."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from olympus.platform.errors import ValidationError

_SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|secret)",
    re.IGNORECASE,
)
_SECRET_TEXT_RE = re.compile(
    r"(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|secret)\s*[:=]",
    re.IGNORECASE,
)
_LONG_TEXT_LIMIT = 800
_SAFE_TRAIT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


def normalize_trait(value: Any) -> str:
    text = re.sub(r"[^a-z0-9_-]+", "_", str(value).strip().lower()).strip("_")
    return text if _SAFE_TRAIT.fullmatch(text) else ""


def safe_trait_list(values: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(values, list | tuple | set):
        values = [values] if values else []
    return list(
        dict.fromkeys(
            trait for trait in (normalize_trait(value) for value in values) if trait
        )
    )[:limit]


def validate_safe_text(value: str, *, field: str, max_chars: int) -> str:
    text = " ".join(value.split())
    if len(text) > max_chars:
        raise ValidationError(
            f"{field} exceeds the local personalization limit.",
            details={"field": field, "max_chars": max_chars},
        )
    if _SECRET_TEXT_RE.search(text):
        raise ValidationError(
            f"{field} appears to contain a secret and was not stored.",
            details={"field": field},
        )
    return text


def assert_privacy_safe(payload: Any, *, path: str = "profile") -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            if _SECRET_KEY_RE.search(key_text):
                raise ValidationError(
                    "Sensitive credential fields are not allowed in personalization data.",
                    details={"field": f"{path}.{key_text}"},
                )
            assert_privacy_safe(value, path=f"{path}.{key_text}")
        return
    if isinstance(payload, list | tuple | set):
        for index, value in enumerate(payload):
            assert_privacy_safe(value, path=f"{path}[{index}]")
        return
    if isinstance(payload, str):
        if len(payload) > _LONG_TEXT_LIMIT:
            raise ValidationError(
                "Long transcript, script, lyric, or document text is not allowed in preferences.",
                details={"field": path, "max_chars": _LONG_TEXT_LIMIT},
            )
        if _SECRET_TEXT_RE.search(payload):
            raise ValidationError(
                "Sensitive credential-like text is not allowed in personalization data.",
                details={"field": path},
            )


def validate_clip_traits(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    source = raw or {}
    allowed = {
        "hook_category",
        "title_pattern",
        "caption_style",
        "music_mood",
        "motion_style",
        "clip_traits",
    }
    result: dict[str, Any] = {}
    for key in allowed:
        if key not in source:
            continue
        if key == "clip_traits":
            result[key] = safe_trait_list(source[key])
        else:
            trait = normalize_trait(source[key])
            if trait:
                result[key] = trait
    return result
