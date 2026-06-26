"""The HTTP API layer.

Contains the FastAPI application factory, middleware, dependency-injection
wiring, and versioned routes. This layer is a thin edge (per the architecture):
it authenticates, validates, reads/writes state, and enqueues work - it does no
heavy processing itself.
"""

from olympus.api.app import create_app

__all__ = ["create_app"]
