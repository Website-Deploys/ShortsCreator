"""Privacy-safe normalization helpers for BOBA project memory."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from olympus.platform.errors import ValidationError

_SECRET_KEY = re.compile(
    r"(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|secret)",
    re.IGNORECASE,
)
_SECRET_TEXT = re.compile(
    r"(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|secret)\s*[:=]",
    re.IGNORECASE,
)


def sanitize_memory_payload(value: Any, *, max_excerpt_chars: int, path: str = "boba") -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if _SECRET_KEY.search(name):
                raise ValidationError(
                    "Sensitive credential fields are not allowed in BOBA memory.",
                    details={"field": f"{path}.{name}"},
                )
            sanitized[name] = sanitize_memory_payload(
                item,
                max_excerpt_chars=max_excerpt_chars,
                path=f"{path}.{name}",
            )
        return sanitized
    if isinstance(value, list | tuple | set):
        return [
            sanitize_memory_payload(
                item,
                max_excerpt_chars=max_excerpt_chars,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, str):
        text = " ".join(value.split())
        if _SECRET_TEXT.search(text):
            raise ValidationError(
                "Credential-like text is not allowed in BOBA memory.",
                details={"field": path},
            )
        if len(text) > max_excerpt_chars:
            if max_excerpt_chars <= 0:
                return ""
            suffix = "…"
            return text[: max_excerpt_chars - len(suffix)].rstrip() + suffix
        return text
    if value is None or isinstance(value, bool | int | float):
        return value
    return sanitize_memory_payload(
        str(value),
        max_excerpt_chars=max_excerpt_chars,
        path=path,
    )


def compact_strings(values: Any, *, limit: int = 12, max_chars: int = 160) -> list[str]:
    if not isinstance(values, list | tuple | set):
        values = [values] if values else []
    result: list[str] = []
    for value in values:
        text = " ".join(str(value).split())
        if not text:
            continue
        text = text[:max_chars].rstrip()
        if text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result
