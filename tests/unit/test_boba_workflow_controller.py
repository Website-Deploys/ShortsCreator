"""BOBA Workflow Controller V1 contracts, graph, routing, API, UI, and validator tests."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from tools.validate_boba_workflow_controller import (
    SCENARIO_NAMES,
    WorkflowSyntheticHarness,
    run_named_scenario,
    run_self_check,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba.integration import BobaIntegration
from olympus.boba.store import BobaMemoryStore
from olympus.boba.workflow_controller import (
    BobaWorkflowArtifactBindingV1,
    BobaWorkflowControllerSetV1,
    BobaWorkflowControllerSignalUsageV1,
    BobaWorkflowControllerSummaryV1,
    BobaWorkflowDefinitionSnapshotV1,
    BobaWorkflowDependencyCheckV1,
    BobaWorkflowEventV1,
    BobaWorkflowExecutionLeaseV1,
    BobaWorkflowHandoffV1,
    BobaWorkflowHumanDecisionV1,
    BobaWorkflowIncidentV1,
    BobaWorkflowPauseRecordV1,
    BobaWorkflowRecoveryHoldV1,
    BobaWorkflowResumeEligibilityReviewV1,
    BobaWorkflowRunV1,
    BobaWorkflowStageDefinitionV1,
    BobaWorkflowStageInstanceV1,
    BobaWorkflowTransitionDecisionV1,
    BobaWorkflowTransitionRequestV1,
    build_workflow_stage_registry,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_workflow_controller_test"
STAGE_IDS = (
    "workflow_created",
    "source_registration",
    "rights_review",
    "source_ready",
    "whole_video_analysis",
    "candidate_discovery",
    "clip_ranking",
    "editorial_selection",
    "creative_direction",
    "clip_brief_generation",
    "hook_retention_planning",
    "caption_motion_planning",
    "music_mood_planning",
    "render_preparation",
    "rendering",
    "technical_validation",
    "output_quality_review",
    "human_review",
    "internal_output_completion",
)
CONTRACT_TYPES: tuple[type[BaseModel], ...] = (
    BobaWorkflowControllerSetV1,
    BobaWorkflowDefinitionSnapshotV1,
    BobaWorkflowStageDefinitionV1,
    BobaWorkflowRunV1,
    BobaWorkflowStageInstanceV1,
    BobaWorkflowArtifactBindingV1,
    BobaWorkflowDependencyCheckV1,
    BobaWorkflowTransitionRequestV1,
    BobaWorkflowTransitionDecisionV1,
    BobaWorkflowPauseRecordV1,
    BobaWorkflowRecoveryHoldV1,
    BobaWorkflowResumeEligibilityReviewV1,
    BobaWorkflowExecutionLeaseV1,
    BobaWorkflowIncidentV1,
    BobaWorkflowHumanDecisionV1,
    BobaWorkflowEventV1,
    BobaWorkflowHandoffV1,
    BobaWorkflowControllerSummaryV1,
    BobaWorkflowControllerSignalUsageV1,
)
PROHIBITED_SIGNAL_FIELDS = (
    "direct_command_execution_used",
    "direct_git_execution_used",
    "direct_ffmpeg_execution_used",
    "arbitrary_dynamic_import_used",
    "arbitrary_function_invocation_used",
    "code_modified_directly",
    "artifact_modified_directly",
    "source_media_modified",
    "accepted_outputs_modified",
    "checkpoint_restore_used",
    "unrestricted_workflow_resume_used",
    "package_installation_used",
    "service_restart_used",
    "process_kill_used",
    "external_api_used",
    "network_access_used",
    "url_fetching_used",
    "scraping_used",
    "downloading_used",
    "uploading_used",
    "publication_used",
    "push_used",
    "merge_used",
    "deployment_used",
    "rights_bypass_used",
    "safety_bypass_used",
    "destructive_action_used",
)
WORKFLOW_ROUTES = (
    ("POST", "/api/v1/boba/projects/{project_id}/workflow-controller/definitions"),
    ("POST", "/api/v1/boba/projects/{project_id}/workflow-controller/runs"),
    ("GET", "/api/v1/boba/projects/{project_id}/workflow-controller"),
    (
        "GET",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/{run_id}",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/"
        "{run_id}/plan-next",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/"
        "{run_id}/transitions",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/{run_id}/"
        "transitions/{transition_id}/evaluate",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/"
        "{run_id}/advance-safe",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/{run_id}/"
        "coordinate-approved-transition",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/{run_id}/pause",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/"
        "{run_id}/continue",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/{run_id}/cancel",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/"
        "{run_id}/recovery-holds",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/"
        "{run_id}/recovery-result",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/{run_id}/"
        "resume-eligibility",
    ),
    (
        "POST",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/"
        "{run_id}/human-decision",
    ),
    (
        "GET",
        "/api/v1/boba/projects/{project_id}/workflow-controller/runs/{run_id}/events",
    ),
    ("GET", "/api/v1/boba/projects/{project_id}/workflow-controller/export"),
    ("DELETE", "/api/v1/boba/projects/{project_id}/workflow-controller"),
)


@pytest.fixture(scope="module")
def workflow_harness(
    tmp_path_factory: pytest.TempPathFactory,
) -> WorkflowSyntheticHarness:
    return WorkflowSyntheticHarness(
        tmp_path_factory.mktemp("boba_workflow_controller_scenarios")
    )


@pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
def test_each_named_workflow_controller_scenario(
    scenario_name: str,
    workflow_harness: WorkflowSyntheticHarness,
) -> None:
    result = run_named_scenario(scenario_name, workflow_harness)
    assert result.passed, result.detail


@pytest.mark.parametrize(
    "contract_type",
    CONTRACT_TYPES,
    ids=lambda value: value.__name__,
)
def test_every_workflow_contract_has_json_safe_schema(
    contract_type: type[BaseModel],
) -> None:
    schema = contract_type.model_json_schema()
    assert schema["title"] == contract_type.__name__
    assert json.loads(json.dumps(schema)) == schema
    assert schema.get("type") == "object"


@pytest.mark.parametrize("stage_id", STAGE_IDS)
def test_every_builtin_stage_is_static_and_cross_linked(stage_id: str) -> None:
    snapshot, stages = build_workflow_stage_registry()
    stage_by_id = {item.stage_id: item for item in stages}
    stage = stage_by_id[stage_id]
    assert tuple(stage_by_id) == STAGE_IDS
    assert stage.stage_definition_id in snapshot.stage_definition_ids
    assert all(
        predecessor in stage_by_id
        for predecessor in stage.required_predecessor_stage_ids
    )
    assert all(successor in stage_by_id for successor in stage.allowed_next_stage_ids)
    if stage.terminal:
        assert not stage.allowed_next_stage_ids
        assert stage.stage_id in snapshot.terminal_stage_ids
    if stage.operation_class == "approved_execution":
        assert stage.target_approval_required is True
        assert stage.safety_gate_required is True
        assert stage.idempotency_required is True


@pytest.mark.parametrize("field_name", PROHIBITED_SIGNAL_FIELDS)
def test_every_prohibited_workflow_signal_is_structurally_false(
    field_name: str,
) -> None:
    signals = BobaWorkflowControllerSignalUsageV1()
    assert getattr(signals, field_name) is False
    with pytest.raises(PydanticValidationError):
        BobaWorkflowControllerSignalUsageV1.model_validate({field_name: True})


@pytest.mark.parametrize(("method", "path"), WORKFLOW_ROUTES)
def test_every_workflow_controller_api_route_is_registered(
    app: FastAPI,
    method: str,
    path: str,
) -> None:
    registered = app.openapi()["paths"]
    assert path in registered
    assert method.casefold() in registered[path]


def _project() -> Project:
    timestamp = utc_now()
    return Project(
        id=PROJECT_ID,
        name="BOBA Workflow Controller Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{PROJECT_ID}/source.mp4",
        size_bytes=24,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=20.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _integration(tmp_path: Path) -> BobaIntegration:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    project = _project()
    asyncio.run(
        storage.put(
            project.storage_key,
            b"synthetic-workflow-source",
            content_type="video/mp4",
        )
    )
    asyncio.run(StorageProjectRepository(storage).save(project))
    return BobaIntegration(storage, BobaMemoryStore(tmp_path / "boba"))


def test_api_creates_and_reads_persisted_workflow_run(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    integration = _integration(tmp_path)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    base = f"/api/v1/boba/projects/{PROJECT_ID}/workflow-controller"
    try:
        with TestClient(app) as client:
            created = client.post(
                f"{base}/runs",
                json={
                    "clip_ids": ["clip_a"],
                    "output_ids_by_clip": {"clip_a": "output_a"},
                    "rights_status": "owned",
                },
            )
            loaded = client.get(base)
    finally:
        app.dependency_overrides.pop(boba_integration_provider, None)
    assert created.status_code == 200, created.text
    assert loaded.status_code == 200, loaded.text
    payload = loaded.json()
    assert payload["schema_version"] == "boba_workflow_controller_v1"
    assert len(payload["workflow_runs"]) == 1
    assert payload["workflow_runs"][0]["upload_authorized"] is False
    assert payload["workflow_runs"][0]["publication_authorized"] is False


def test_validator_self_check_and_exact_scenario_catalog() -> None:
    report = run_self_check()
    assert report.passed
    assert len(SCENARIO_NAMES) == 201
    assert len(set(SCENARIO_NAMES)) == 201
    assert SCENARIO_NAMES[0] == "001_built_in_workflow_definition_created"
    assert SCENARIO_NAMES[-1] == "201_no_destructive_action"


def test_documentation_has_exactly_thirty_five_numbered_sections() -> None:
    source = Path("docs/BOBA_WORKFLOW_CONTROLLER_V1.md").read_text(
        encoding="utf-8"
    )
    sections = re.findall(r"^## (\d+)\. (.+)$", source, flags=re.MULTILINE)
    assert [int(number) for number, _title in sections] == list(range(1, 36))
    assert sections[0][1] == "Purpose"
    assert sections[-1][1] == "Limitations"


def test_frontend_panel_exposes_truthful_workflow_sections_and_controls() -> None:
    source = Path(
        "frontend/src/components/project/BobaWorkflowControllerPanel.tsx"
    ).read_text(encoding="utf-8")
    required_labels = (
        "WORKFLOW",
        "CURRENT STAGE",
        "PROJECT STAGES",
        "CLIP STAGES",
        "DEPENDENCIES",
        "ARTIFACTS",
        "PAUSE AND RECOVERY",
        "VALIDATION AND QUALITY",
        "SAFETY AND APPROVAL",
        "NEXT INTERNAL TRANSITION",
        "HUMAN DECISION",
        "LIVE WORKFLOW FEED",
        "Create workflow run",
        "Plan next stage",
        "Review transition",
        "Advance safe read-only stage",
        "Coordinate exact approved transition",
        "Pause workflow",
        "Continue controller",
        "Cancel workflow",
    )
    assert all(label in source for label in required_labels)
    prohibited_controls = (
        "Resume everything",
        "Ignore Safety",
        "Force publish",
        "Force upload",
    )
    assert all(label not in source for label in prohibited_controls)


def test_results_section_mounts_workflow_panel_in_all_result_states() -> None:
    source = Path(
        "frontend/src/components/project/ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BobaWorkflowControllerPanel" in source
    assert source.count("<BobaWorkflowControllerPanel") == 1
    assert source.count("{workflowControllerPanel}") >= 4


def test_controller_source_has_no_direct_process_or_dynamic_invocation() -> None:
    source = Path("src/olympus/boba/workflow_controller.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"(?m)^\s*(?:from|import)\s+subprocess\b", source)
    assert not re.search(r"(?m)^\s*(?:from|import)\s+importlib\b", source)
    assert not re.search(r"\bos\.system\s*\(", source)
    assert not re.search(r"\b(?:eval|exec|__import__)\s*\(", source)


def test_controller_does_not_expose_generic_resume_authority() -> None:
    source = Path("src/olympus/boba/workflow_controller.py").read_text(
        encoding="utf-8"
    )
    assert "unrestricted_workflow_resume_used: Literal[False]" in source
    assert "workflow_resume_authorized: Literal[False]" in source
