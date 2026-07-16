"""Aggregate router for API v1.

Collects the individual route modules into a single router mounted by the app
factory. Business resource routers (projects, clips, exports) are added here in
later milestones.
"""

from __future__ import annotations

from fastapi import APIRouter

from olympus.api.v1.routes import (
    analysis,
    editing,
    health,
    jobs,
    library,
    monitoring,
    optimization,
    personalization,
    planning,
    projects,
    rendering,
    story,
    system,
    uploads,
    virality,
    workflow,
)

api_v1_router = APIRouter()
api_v1_router.include_router(health.router, tags=["health"])
api_v1_router.include_router(system.router, tags=["system"])
api_v1_router.include_router(uploads.router, tags=["uploads"])
api_v1_router.include_router(projects.router)
api_v1_router.include_router(jobs.router)
api_v1_router.include_router(jobs.project_router)
api_v1_router.include_router(analysis.router)
api_v1_router.include_router(story.router)
api_v1_router.include_router(virality.router)
api_v1_router.include_router(planning.router)
api_v1_router.include_router(editing.router)
api_v1_router.include_router(rendering.router)
api_v1_router.include_router(optimization.router)
api_v1_router.include_router(personalization.router)
api_v1_router.include_router(workflow.router)
api_v1_router.include_router(workflow.ops_router)
api_v1_router.include_router(library.router)
api_v1_router.include_router(monitoring.router)
