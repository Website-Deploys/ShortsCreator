"""ASGI entry point for the backend API.

Exposes the module-level ``app`` that an ASGI server (uvicorn) serves, e.g.::

    uvicorn olympus.apps.backend_api.main:app

and a ``run()`` helper (wired to the ``olympus-api`` console script) for local
convenience.
"""

from __future__ import annotations

from olympus.api import create_app
from olympus.platform.config import get_settings

# The ASGI application instance served in all environments.
app = create_app()


def run() -> None:
    """Run the API with uvicorn (development convenience)."""

    import uvicorn

    settings = get_settings()
    reload_enabled = not settings.is_production
    uvicorn.run(
        "olympus.apps.backend_api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        reload=reload_enabled,
        reload_excludes=[
            "storage_data/*",
            "work/*",
            ".venv/*",
            "frontend/.next/*",
            "frontend/node_modules/*",
            "render/*",
        ]
        if reload_enabled
        else None,
        log_config=None,  # our structlog config owns logging.
    )


if __name__ == "__main__":
    run()
