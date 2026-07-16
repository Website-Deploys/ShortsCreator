"""Privacy, secret, copyright, and payload checks for BOBA memory."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from olympus.boba.memory_contracts import BobaMemoryRecordV1
from olympus.platform.errors import ValidationError

_SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|cookie|secret)",
    re.IGNORECASE,
)
_SECRET_TEXT_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{4,}", re.IGNORECASE),
    re.compile(r"\bghp_[A-Za-z0-9_-]{4,}", re.IGNORECASE),
    re.compile(r"\bxoxb-[A-Za-z0-9_-]{4,}", re.IGNORECASE),
    re.compile(
        r"(?:api[_-]?key|password|passwd|cookie|access[_-]?token|refresh[_-]?token)\s*[:=]",
        re.IGNORECASE,
    ),
    re.compile(r"\bbearer\s+(?:token|[A-Za-z0-9._-]{8,})", re.IGNORECASE),
)
_MEDIA_OR_BINARY_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|file://|https?://)[^\s]+\.(?:mp4|mov|mkv|avi|webm|mp3|wav|aac|flac|png|jpe?g|gif|zip|exe|dll)(?:\?|$)",
    re.IGNORECASE,
)
_SPEAKER_LINE_RE = re.compile(r"(?:^|\n)\s*(?:speaker\s*\d+|[A-Z][A-Z ]{1,24}):", re.MULTILINE)


def detect_secret_like_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_TEXT_PATTERNS)


def detect_copyright_risk_text(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) > 5_000:
        return True
    words = stripped.split()
    if len(stripped) > 1_500 and len(words) > 250:
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(stripped) > 600 and len(lines) >= 8:
        return True
    return len(_SPEAKER_LINE_RE.findall(stripped)) >= 8


def sanitize_memory_text(text: str) -> str:
    if detect_secret_like_text(text):
        raise ValidationError("Secret-like text is not allowed in BOBA memory.")
    if _MEDIA_OR_BINARY_PATH_RE.search(text):
        raise ValidationError("Media or binary paths are not allowed as BOBA memory content.")
    return " ".join(text.split())


def truncate_safe_excerpt(text: str, *, max_chars: int = 300) -> str:
    sanitized = sanitize_memory_text(text)
    if detect_copyright_risk_text(text):
        raise ValidationError("Long transcript, lyric, caption, or copied text is not allowed.")
    if len(sanitized) <= max_chars:
        return sanitized
    return sanitized[: max(0, max_chars - 3)].rstrip() + "..."


def _validate_payload(value: Any, *, path: str = "memory") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if _SECRET_KEY_RE.search(name):
                raise ValidationError(
                    "Sensitive credential fields are not allowed in BOBA memory.",
                    details={"field": f"{path}.{name}"},
                )
            _validate_payload(item, path=f"{path}.{name}")
        return
    if isinstance(value, list | tuple | set):
        for index, item in enumerate(value):
            _validate_payload(item, path=f"{path}[{index}]")
        return
    if isinstance(value, bytes | bytearray | memoryview):
        raise ValidationError("Binary content is not allowed in BOBA memory.")
    if isinstance(value, str):
        if detect_secret_like_text(value):
            raise ValidationError(
                "Secret-like text is not allowed in BOBA memory.",
                details={"field": path},
            )
        if _MEDIA_OR_BINARY_PATH_RE.search(value):
            raise ValidationError(
                "Media or binary paths are not allowed as BOBA memory content.",
                details={"field": path},
            )
        if detect_copyright_risk_text(value):
            raise ValidationError(
                "Long transcript, lyric, caption, or copied text is not allowed in BOBA memory.",
                details={"field": path},
            )


def validate_memory_record(
    record: BobaMemoryRecordV1 | Mapping[str, Any],
    *,
    max_excerpt_chars: int = 300,
) -> BobaMemoryRecordV1:
    validated = (
        record.model_copy(deep=True)
        if isinstance(record, BobaMemoryRecordV1)
        else BobaMemoryRecordV1.model_validate(record)
    )
    _validate_payload(validated.model_dump(mode="json"))
    excerpt = truncate_safe_excerpt(validated.safe_excerpt, max_chars=max_excerpt_chars)
    if excerpt != validated.safe_excerpt:
        validated.warnings = list(
            dict.fromkeys([*validated.warnings, "safe_excerpt_truncated"])
        )
    validated.safe_excerpt = excerpt
    validated.summary = sanitize_memory_text(validated.summary)
    validated.evidence = [sanitize_memory_text(item) for item in validated.evidence]
    validated.tags = [sanitize_memory_text(item).lower()[:80] for item in validated.tags]
    validated.warnings = [sanitize_memory_text(item) for item in validated.warnings]
    return validated


def validate_memory_export(
    payload: Mapping[str, Any], *, max_bytes: int = 10_000_000
) -> dict[str, Any]:
    loaded = json.loads(json.dumps(payload, ensure_ascii=False))
    if not isinstance(loaded, dict):
        raise ValidationError("BOBA memory export payload must be an object.")
    serializable: dict[str, Any] = loaded
    encoded = json.dumps(serializable, ensure_ascii=False).encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValidationError(
            "BOBA memory export exceeds the configured size limit.",
            details={"max_bytes": max_bytes},
        )
    _validate_payload(serializable, path="export")
    return serializable
