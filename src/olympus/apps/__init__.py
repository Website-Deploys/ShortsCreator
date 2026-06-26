"""Deployable application entry points.

Each subpackage is an independently-deployable process:
- ``backend_api`` - the synchronous HTTP edge (the FastAPI/ASGI app).
- ``workers``     - the asynchronous processing core (the Celery worker).

These modules only *compose and launch* the pieces wired elsewhere; they hold no
logic of their own.
"""
