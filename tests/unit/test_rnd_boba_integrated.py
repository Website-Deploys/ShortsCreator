"""Integrated R&D proof for BOBA Core and Memory working together."""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.validate_rnd_boba_integrated import (
    REPORT_DIRECTORY,
    REPORT_JSON,
    REPORT_MARKDOWN,
    RndBobaIntegratedReport,
    run_integrated_rnd_validation,
)


@pytest.fixture(scope="session")
def integrated_rnd_result(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[RndBobaIntegratedReport, Path]:
    workspace = tmp_path_factory.mktemp("rnd_boba_integrated")
    report = run_integrated_rnd_validation(workspace)
    return report, workspace


def test_integrated_rnd_validator_creates_synthetic_project(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.project_id.startswith("rnd_boba_project_")
    assert report.production_projects_modified is False


def test_integrated_brain_state_is_created(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.brain_created
    assert report.constitution_checked
    assert report.contracts_checked
    assert report.reasoning_checked
    assert report.observations_created >= 3


def test_decision_bus_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.decision_bus_checked
    assert report.decisions_created >= 2


def test_ranking_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.ranking_checked


def test_editorial_policy_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.editorial_policy_checked


def test_project_memory_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.project_memory_checked


def test_creator_memory_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.creator_memory_checked


def test_global_memory_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.global_memory_checked


def test_retrieval_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.retrieval_checked


def test_learning_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.learning_checked


def test_memory_application_works_inside_integrated_scenario(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.memory_application_checked


def test_compact_boba_truth_is_attached(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.integration_checked
    assert report.compact_truth_attached
    assert report.api_surface_checked
    assert report.frontend_types_checked
    assert report.cli_surface_checked


def test_unsafe_memory_is_blocked(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.unsafe_content_blocked
    assert report.long_excerpt_truncated


def test_no_external_calls_are_made(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.external_calls_made is False


def test_no_real_media_is_used(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, _workspace = integrated_rnd_result
    assert report.real_media_used is False


def test_reports_are_written_only_under_rnd_validation(
    integrated_rnd_result: tuple[RndBobaIntegratedReport, Path],
) -> None:
    report, workspace = integrated_rnd_result
    output_directory = (workspace / REPORT_DIRECTORY).resolve()
    json_path = (output_directory / REPORT_JSON).resolve()
    markdown_path = (output_directory / REPORT_MARKDOWN).resolve()
    assert report.passed, report.errors
    assert json_path.is_file()
    assert markdown_path.is_file()
    assert json_path.is_relative_to(output_directory)
    assert markdown_path.is_relative_to(output_directory)
    assert sorted(path.name for path in output_directory.iterdir()) == sorted(
        [REPORT_JSON, REPORT_MARKDOWN]
    )
