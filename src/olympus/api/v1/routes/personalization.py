"""Local-only Creator Personalization V2 profile and feedback endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from olympus.api.dependencies import PersonalizationServiceDep, ProjectServiceDep, SettingsDep
from olympus.api.v1.schemas.personalization import (
    ActivateProfileRequest,
    CreateProfileRequest,
    ImportProfileRequest,
    ResetProfileRequest,
    SubmitFeedbackRequest,
    UpdateProfileRequest,
)
from olympus.platform.errors import ValidationError

router = APIRouter(prefix="/personalization", tags=["personalization"])


@router.get("/profiles")
def list_profiles(service: PersonalizationServiceDep) -> dict[str, Any]:
    profiles = [profile.model_dump(mode="json") for profile in service.list_profiles()]
    summary = service.summary()
    return {
        "profiles": profiles,
        "active_profile_id": summary["active_profile"]["profile_id"],
        "presets": summary["presets"],
        "privacy": summary["privacy"],
    }


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
def create_profile(
    body: CreateProfileRequest,
    service: PersonalizationServiceDep,
) -> dict[str, Any]:
    profile = service.create_profile(
        body.preset_id,
        profile_name=body.profile_name,
        learning_enabled=body.learning_enabled,
        activate=body.activate,
    )
    return profile.model_dump(mode="json")


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, service: PersonalizationServiceDep) -> dict[str, Any]:
    return service.get_profile(profile_id).model_dump(mode="json")


@router.patch("/profiles/{profile_id}")
def update_profile(
    profile_id: str,
    body: UpdateProfileRequest,
    service: PersonalizationServiceDep,
) -> dict[str, Any]:
    return service.update_profile(profile_id, body.updates).model_dump(mode="json")


@router.post("/profiles/{profile_id}/activate")
def activate_profile(
    profile_id: str,
    body: ActivateProfileRequest,
    service: PersonalizationServiceDep,
) -> dict[str, Any]:
    if not body.confirm:
        raise ValidationError("Profile activation requires explicit confirmation.")
    return service.activate_profile(profile_id).model_dump(mode="json")


@router.post("/profiles/{profile_id}/reset")
def reset_profile(
    profile_id: str,
    body: ResetProfileRequest,
    service: PersonalizationServiceDep,
) -> dict[str, Any]:
    if not body.confirm:
        raise ValidationError("Profile reset requires explicit confirmation.")
    return service.reset_profile(profile_id).model_dump(mode="json")


@router.get("/profiles/{profile_id}/export")
def export_profile(
    profile_id: str,
    service: PersonalizationServiceDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    if not settings.creator_personalization.allow_export_import:
        raise ValidationError("Creator profile export is disabled by configuration.")
    return service.export_profile(profile_id)


@router.post("/profiles/import", status_code=status.HTTP_201_CREATED)
def import_profile(
    body: ImportProfileRequest,
    service: PersonalizationServiceDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    if not settings.creator_personalization.allow_export_import:
        raise ValidationError("Creator profile import is disabled by configuration.")
    return service.import_profile(body.profile, activate=body.activate).model_dump(mode="json")


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    body: SubmitFeedbackRequest,
    service: PersonalizationServiceDep,
    projects: ProjectServiceDep,
) -> dict[str, Any]:
    await projects.get(body.project_id)
    feedback = service.record_feedback(
        profile_id=body.profile_id,
        project_id=body.project_id,
        clip_id=body.clip_id,
        rating=body.rating.model_dump(mode="json"),
        labels=[str(label) for label in body.labels],
        notes=body.notes,
        clip_traits=body.clip_traits.model_dump(mode="json", exclude_none=True),
    )
    return feedback.model_dump(mode="json")


@router.get("/summary")
def personalization_summary(service: PersonalizationServiceDep) -> dict[str, Any]:
    return service.summary()
