from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tools import validate_real_rendering_e2e as validator

from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.workflow import Job, JobStatus, Workflow, WorkflowStatus
from olympus.rendering.artifacts import (
    canonical_render_manifest_path,
    legacy_render_manifest_path,
)
from olympus.utils import utc_now


def _probe(**overrides: Any) -> dict[str, Any]:
    return {
        "passed": True,
        "container_duration": 24.0,
        "video_duration": 24.0,
        "audio_duration": 24.0,
        "width": 1080,
        "height": 1920,
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_sample_rate": 48000,
        "has_audio": True,
        **overrides,
    }


def _render(project_id: str, *, key: str | None = None) -> dict[str, Any]:
    return {
        "clip_id": "clip_one",
        "storage_key": key or f"render/{project_id}/clips/clip_one.mp4",
        "duration": 24.0,
        "metadata": {
            "timeline": {"contract_version": "1", "repaired_start_seconds": 0.0},
            "editing_v2": {"boundary_quality": {"quality_score": 0.9}},
            "caption_render_validation": {"passed": True},
            "unified_clip_intelligence": {
                "story": {"story_shape": "problem_solution"},
                "virality": {"hook_line": "A deterministic hook"},
                "planning": {"selected_reason": "Complete local fixture"},
            },
        },
    }


async def _write_manifest(
    storage: LocalStorage,
    project_id: str,
    *,
    canonical: bool = True,
    include_mp4: bool = True,
    mp4_bytes: bytes = b"x" * 2048,
) -> dict[str, Any]:
    render = _render(project_id)
    if include_mp4:
        await storage.put(render["storage_key"], mp4_bytes, content_type="video/mp4")
    manifest = {
        "project_id": project_id,
        "status": "completed",
        "renders": [render],
    }
    path = (
        canonical_render_manifest_path(project_id)
        if canonical
        else legacy_render_manifest_path(project_id)
    )
    payload = (
        {
            "project_id": project_id,
            "pipeline_version": "1",
            "status": "completed",
            "stages": [],
            "render_manifest": manifest,
        }
        if canonical
        else manifest
    )
    await storage.put(path, json.dumps(payload).encode(), content_type="application/json")
    return render


def _clip(
    tmp_path: Path,
    *,
    render: dict[str, Any] | None = None,
    probe: dict[str, Any] | None = None,
    payload: bytes = b"x" * 2048,
) -> dict[str, Any]:
    storage_root = tmp_path / "storage"
    storage = LocalStorage(root=str(storage_root))
    item = render or _render("project")
    asyncio.run(storage.put(item["storage_key"], payload, content_type="video/mp4"))
    return validator.inspect_rendered_clip(
        render=item,
        storage=storage,
        storage_root=storage_root,
        captions_enabled=True,
        probe_function=lambda _path: probe or _probe(),
    )


def test_synthetic_fixture_generator_creates_safe_local_media_plan(tmp_path: Path) -> None:
    command = validator.synthetic_media_plan(tmp_path / "fixture.mp4")
    transcript = validator.synthetic_transcript(validator.SYNTHETIC_DURATION_SECONDS)

    assert "lavfi" in command
    assert "color=c=" in " ".join(command)
    assert "drawbox" in " ".join(command)
    assert "sine=" in " ".join(command)
    assert not any("http://" in item or "https://" in item for item in command)
    assert 60.0 <= validator.SYNTHETIC_DURATION_SECONDS <= 120.0
    assert max(segment.end for segment in transcript.segments) <= 8.0


def test_validator_defaults_to_bounded_renderer_profile() -> None:
    args = validator._parser().parse_args(["--local-synthetic"])

    assert args.render_preset == "veryfast"
    assert args.render_threads == 2
    assert args.render_filter_threads == 1


def test_api_payload_accepts_completed_workflow_artifacts_when_project_is_analyzed(
    monkeypatch: Any,
) -> None:
    class FakeResponse:
        @classmethod
        def from_entity(cls, _entity: Any) -> FakeResponse:
            return cls()

        def model_dump(self, *, mode: str) -> dict[str, str]:
            return {"mode": mode}

    monkeypatch.setattr(validator, "ProjectResponse", FakeResponse)
    monkeypatch.setattr(validator, "RenderRunResponse", FakeResponse)
    monkeypatch.setattr(validator, "RenderManifestResponse", FakeResponse)
    monkeypatch.setattr(validator, "OptimizationResponse", FakeResponse)
    monkeypatch.setattr(
        validator,
        "validate_frontend_payload",
        lambda **_kwargs: {"passed": True, "warnings": []},
    )
    completed = SimpleNamespace(status=SimpleNamespace(value="completed"))
    project = SimpleNamespace(id="project", status=SimpleNamespace(value="analyzed"))
    manifest = SimpleNamespace(renders=[{"clip_id": "clip"}])
    clips = [
        {
            "clip_id": "clip",
            "download_url": "/download/{project_id}/clip",
            "downloadable": True,
            "timeline_metadata_present": True,
            "boundary_quality_present": True,
        }
    ]

    result = validator._api_payload_validation(
        project=project,
        render_run=completed,
        manifest=manifest,
        optimization=completed,
        plans=[],
        clips=clips,
    )

    assert result["valid"] is True
    assert result["frontend_valid"] is True
    assert result["project_status"] == "analyzed"
    assert any("durable workflow" in warning for warning in result["warnings"])


def test_report_schema_serializes() -> None:
    report = validator.base_report("local_synthetic", "project")

    serialized = json.loads(json.dumps(report))

    assert serialized["project_id"] == "project"
    assert set(serialized["stages"]) == {
        "analysis",
        "story",
        "virality",
        "planning",
        "editing",
        "rendering",
        "optimization",
    }


def test_missing_render_manifest_fails_validation(tmp_path: Path) -> None:
    result = asyncio.run(
        validator.inspect_render_bundle(
            storage=LocalStorage(root=str(tmp_path)),
            storage_root=tmp_path,
            project_id="missing",
            captions_enabled=True,
            probe_function=lambda _path: _probe(),
        )
    )

    assert result["valid"] is False
    assert result["canonical_present"] is False


def test_stale_legacy_render_path_warns(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    asyncio.run(_write_manifest(storage, "legacy", canonical=False))

    result = asyncio.run(
        validator.inspect_render_bundle(
            storage=storage,
            storage_root=tmp_path,
            project_id="legacy",
            captions_enabled=True,
            probe_function=lambda _path: _probe(),
        )
    )

    assert result["valid"] is False
    assert any("legacy" in warning.lower() for warning in result["warnings"])


def test_canonical_render_manifest_passes(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    asyncio.run(_write_manifest(storage, "canonical"))

    result = asyncio.run(
        validator.inspect_render_bundle(
            storage=storage,
            storage_root=tmp_path,
            project_id="canonical",
            captions_enabled=True,
            probe_function=lambda _path: _probe(),
        )
    )

    assert result["valid"] is True
    assert result["artifact_path"] == canonical_render_manifest_path("canonical")


def test_missing_mp4_fails_validation(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    asyncio.run(_write_manifest(storage, "missing_mp4", include_mp4=False))

    result = asyncio.run(
        validator.inspect_render_bundle(
            storage=storage,
            storage_root=tmp_path,
            project_id="missing_mp4",
            captions_enabled=True,
            probe_function=lambda _path: _probe(),
        )
    )

    assert result["valid"] is False
    assert result["clips"][0]["exists"] is False


def test_zero_byte_mp4_fails_validation(tmp_path: Path) -> None:
    result = _clip(tmp_path, payload=b"")

    assert result["passed"] is False
    assert any("minimum" in error for error in result["errors"])


def test_mp4_without_audio_fails_validation(tmp_path: Path) -> None:
    result = _clip(
        tmp_path,
        probe=_probe(has_audio=False, audio_codec=None, audio_duration=None),
    )

    assert result["audio_stream"] is False
    assert result["passed"] is False


def test_mp4_without_video_fails_validation(tmp_path: Path) -> None:
    result = _clip(tmp_path, probe=_probe(width=None, height=None, video_codec=None))

    assert result["video_stream"] is False
    assert result["passed"] is False


def test_missing_timeline_metadata_fails_validation(tmp_path: Path) -> None:
    render = _render("timeline")
    render["metadata"].pop("timeline")

    result = _clip(tmp_path, render=render)

    assert result["timeline_metadata_present"] is False
    assert result["passed"] is False


def test_missing_boundary_quality_metadata_fails_validation(tmp_path: Path) -> None:
    render = _render("boundary")
    render["metadata"]["editing_v2"] = {}

    result = _clip(tmp_path, render=render)

    assert result["boundary_quality_present"] is False
    assert result["passed"] is False


def test_optimization_blocked_before_render_manifest_fails() -> None:
    now = utc_now()
    workflow = Workflow(
        workflow_id="workflow",
        project_id="project",
        status=WorkflowStatus.FAILED,
        created_at=now,
        updated_at=now,
        jobs=[
            Job(
                job_id="render",
                workflow_id="workflow",
                project_id="project",
                engine="rendering",
                stage="rendering",
                status=JobStatus.DEAD,
                created_at=now,
                finished_at=now,
            ),
            Job(
                job_id="optimize",
                workflow_id="workflow",
                project_id="project",
                engine="optimization",
                stage="optimization",
                status=JobStatus.BLOCKED,
                depends_on=("rendering",),
                created_at=now,
            ),
        ],
    )

    result = validator.validate_optimization_handoff(
        workflow,
        render_checkpoint_valid=False,
    )

    assert result["passed"] is False
    assert result["optimization_status"] == "blocked"


def test_project_id_inspection_does_not_run_pipeline(
    monkeypatch: Any,
) -> None:
    called = {"inspect": 0, "pipeline": 0}

    async def fake_inspect(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        called["inspect"] += 1
        return validator.base_report("project_id", "existing")

    async def forbidden_pipeline(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        called["pipeline"] += 1
        raise AssertionError("project inspection must not run the pipeline")

    monkeypatch.setattr(validator, "inspect_existing_project", fake_inspect)
    monkeypatch.setattr(validator, "run_local_pipeline", forbidden_pipeline)
    args = argparse.Namespace(
        project_id="existing",
        local_synthetic=False,
        local_file=None,
        storage_root=Path("storage_data"),
        report_dir=validator.DEFAULT_REPORT_DIR,
        ffmpeg_binary="ffmpeg",
        ffprobe_binary="ffprobe",
        timeout_seconds=1.0,
        minimum_mp4_bytes=1,
    )

    asyncio.run(validator.run_selected_mode(args))

    assert called == {"inspect": 1, "pipeline": 0}


def test_validator_writes_reports_under_work_only(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    output = tmp_path / "work" / "validation_reports" / "real_rendering_e2e"

    paths = validator.write_reports(validator.base_report("local_synthetic"), output)

    assert Path(paths["json"]).is_relative_to(tmp_path / "work" / "validation_reports")
    assert Path(paths["summary"]).is_file()


def test_synthetic_mode_makes_no_external_calls() -> None:
    report = validator.base_report("local_synthetic")
    command = validator.synthetic_media_plan(Path("work/fixture.mp4"))

    assert report["external_calls_made"] is False
    assert not any("://" in item for item in command)


def test_synthetic_mode_requires_no_real_user_media() -> None:
    report = validator.base_report("local_synthetic")
    transcript = validator.synthetic_transcript(validator.SYNTHETIC_DURATION_SECONDS)

    assert report["real_user_media_used"] is False
    assert transcript.segments
    assert transcript.confidence == 0.99
