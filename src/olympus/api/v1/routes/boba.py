"""Inspection-only API routes for BOBA Core Brain V1."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from olympus.api.dependencies import BobaIntegrationDep, SettingsDep
from olympus.platform.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/boba", tags=["boba"])


class EditorialPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str = Field(min_length=1, max_length=128)


def _require_enabled(settings: SettingsDep) -> None:
    if not settings.boba.enabled:
        raise ValidationError("BOBA Core Brain is disabled by configuration.")


async def _require_project(project_id: str, boba: BobaIntegrationDep) -> None:
    if await boba.projects.get(project_id) is None:
        raise NotFoundError("Project was not found.", details={"id": project_id})


@router.get("/projects/{project_id}/brain")
async def get_brain(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    state = boba.store.load_brain_state(project_id)
    if state is None:
        state = await boba.generate_boba_for_project(project_id)
    return state.model_dump(mode="json")


@router.get("/projects/{project_id}/decisions")
async def get_decisions(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decisions = boba.store.list_decisions(project_id)
    return {
        "project_id": project_id,
        "mode": "advisory",
        "count": len(decisions),
        "decisions": [item.model_dump(mode="json") for item in decisions],
    }


@router.get("/projects/{project_id}/observations")
async def get_observations(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    observations = boba.store.list_observations(project_id)
    return {
        "project_id": project_id,
        "count": len(observations),
        "observations": [item.model_dump(mode="json") for item in observations],
    }


@router.post("/projects/{project_id}/summarize")
async def summarize_project(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    state = await boba.generate_boba_for_project(project_id)
    return {
        "brain": state.model_dump(mode="json"),
        "summary": boba.brain.summarize_current_state(project_id),
    }


@router.post("/projects/{project_id}/rank-candidates")
async def rank_project_candidates(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_candidate_ranking:
        raise ValidationError("BOBA candidate ranking is disabled by configuration.")
    await _require_project(project_id, boba)
    return (await boba.rank_project_candidates(project_id)).model_dump(mode="json")


@router.post("/projects/{project_id}/editorial-policy")
async def create_project_editorial_policy(
    project_id: str,
    body: EditorialPolicyRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_editorial_policy:
        raise ValidationError("BOBA editorial policy is disabled by configuration.")
    await _require_project(project_id, boba)
    return (await boba.generate_boba_for_clip(project_id, body.clip_id)).model_dump(
        mode="json"
    )
