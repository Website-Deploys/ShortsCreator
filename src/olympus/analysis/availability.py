"""Local capability discovery for optional analysis providers."""

from __future__ import annotations

import importlib.util
import shutil
from typing import Any


def module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def analysis_capabilities() -> dict[str, Any]:
    """Return dependency truth without importing heavy optional packages."""

    opencv = module_available("cv2")
    pytesseract = module_available("pytesseract")
    easyocr = module_available("easyocr")
    pyannote = module_available("pyannote.audio")
    ultralytics = module_available("ultralytics")
    torchvision = module_available("torchvision")
    tesseract_binary = shutil.which("tesseract")
    return {
        "ffmpeg": {"available": shutil.which("ffmpeg") is not None, "provider": "binary"},
        "ffprobe": {"available": shutil.which("ffprobe") is not None, "provider": "binary"},
        "face_detection": {
            "available": False,
            "dependency_available": opencv,
            "provider": "opencv" if opencv else "none",
            "reason": "model_missing" if opencv else "dependency_missing",
        },
        "ocr": {
            "available": False,
            "dependency_available": bool(easyocr or (pytesseract and tesseract_binary)),
            "provider": "easyocr" if easyocr else "pytesseract" if pytesseract else "none",
            "reason": "model_missing"
            if easyocr or (pytesseract and tesseract_binary)
            else "dependency_missing",
        },
        "speaker_diarization": {
            "available": False,
            "dependency_available": pyannote,
            "provider": "pyannote" if pyannote else "none",
            "reason": "model_missing" if pyannote else "dependency_missing",
        },
        "object_detection": {
            "available": False,
            "dependency_available": bool(ultralytics or torchvision),
            "provider": "ultralytics" if ultralytics else "torchvision" if torchvision else "none",
            "reason": "model_missing" if ultralytics or torchvision else "dependency_missing",
        },
    }
