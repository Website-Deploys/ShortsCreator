"""Availability and loading helpers for optional Olympus dependencies."""

from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from typing import Final, TypedDict

from olympus.platform.errors.exceptions import ConfigurationError


class OptionalDependencySpec(TypedDict):
    """Static metadata for one optional import."""

    distribution: str
    feature: str
    extra: str | None


class OptionalDependencyStatus(TypedDict):
    """JSON-safe availability result for one optional import."""

    module: str
    distribution: str
    feature: str
    extra: str | None
    available: bool
    required: bool


OPTIONAL_DEPENDENCIES: Final[dict[str, OptionalDependencySpec]] = {
    "faster_whisper": {
        "distribution": "faster-whisper",
        "feature": "real local transcription",
        "extra": "transcription",
    },
    "ctranslate2": {
        "distribution": "ctranslate2",
        "feature": "faster-whisper inference and CUDA discovery",
        "extra": "transcription",
    },
    "cv2": {
        "distribution": "opencv-python",
        "feature": "local computer-vision analysis",
        "extra": "vision",
    },
    "pytesseract": {
        "distribution": "pytesseract",
        "feature": "optional OCR analysis",
        "extra": None,
    },
    "easyocr": {
        "distribution": "easyocr",
        "feature": "optional OCR analysis",
        "extra": None,
    },
    "pyannote.audio": {
        "distribution": "pyannote.audio",
        "feature": "optional speaker diarization",
        "extra": None,
    },
    "ultralytics": {
        "distribution": "ultralytics",
        "feature": "optional object detection",
        "extra": None,
    },
    "torchvision": {
        "distribution": "torchvision",
        "feature": "optional object detection",
        "extra": None,
    },
    "yt_dlp": {
        "distribution": "yt-dlp",
        "feature": "video-link ingestion",
        "extra": "video-links",
    },
}


def is_module_available(name: str) -> bool:
    """Return dependency truth without importing or initializing the package."""

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def get_optional_dependency_status() -> dict[str, OptionalDependencyStatus]:
    """Return a deterministic, JSON-safe inventory of known optional packages."""

    return {
        name: {
            "module": name,
            "distribution": spec["distribution"],
            "feature": spec["feature"],
            "extra": spec["extra"],
            "available": is_module_available(name),
            "required": False,
        }
        for name, spec in OPTIONAL_DEPENDENCIES.items()
    }


def require_optional_dependency(name: str, feature_name: str) -> ModuleType:
    """Import an optional package or raise an actionable configuration error."""

    spec = OPTIONAL_DEPENDENCIES.get(name)
    try:
        return importlib.import_module(name)
    except (ImportError, ModuleNotFoundError, ValueError) as exc:
        distribution = spec["distribution"] if spec else name
        extra = spec["extra"] if spec else None
        install_hint = (
            f' Install it with `pip install -e ".[{extra}]"`.' if extra else ""
        )
        raise ConfigurationError(
            f"{feature_name} requires optional dependency {distribution!r}, but it is "
            f"not available.{install_hint}",
            details={
                "dependency": name,
                "distribution": distribution,
                "feature": feature_name,
                "extra": extra,
                "available": False,
            },
        ) from exc
