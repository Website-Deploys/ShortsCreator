"""System information endpoint.

``GET /system/info`` returns non-sensitive runtime metadata (version,
environment, and which adapters are active). Useful for verifying a deployment
and for support. It deliberately exposes *no* secrets or connection strings.
"""

from __future__ import annotations

from fastapi import APIRouter

from olympus import __version__
from olympus.api.dependencies import SettingsDep

router = APIRouter()


@router.get("/system/info", summary="Runtime information")
async def system_info(settings: SettingsDep) -> dict[str, object]:
    """Return non-sensitive runtime metadata."""

    return {
        "name": "Project Olympus API",
        "version": __version__,
        "environment": settings.environment.value,
        "adapters": {
            "storage": settings.storage.backend.value,
            "transcription": settings.ai.transcription_provider,
            "rendering": settings.rendering.backend,
        },
    }
