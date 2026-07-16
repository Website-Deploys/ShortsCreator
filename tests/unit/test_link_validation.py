"""Tests for the Real YouTube Link Validation Fix V2 CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tools import validate_link_ingestion as validator

from olympus.services.intake import LinkDownloadRecord, LinkDownloadStatus
from olympus.services.intake.service import UploadRecord


def _report(
    *,
    mode: str = "metadata_only",
    execution: str = "direct",
    rights: bool = True,
) -> dict[str, Any]:
    return validator._empty_report(
        url="https://youtu.be/Owned01",
        mode=mode,
        backend_url="http://127.0.0.1:8000",
        rights_confirmed=rights,
        execution_mode=execution,
    )


def _environment_ready(report: dict[str, Any]) -> None:
    environment = validator._summary(report)["environment"]
    environment.update(
        {
            "olympus_imported": True,
            "ytdlp_installed": True,
            "ytdlp_version": "test",
            "ffmpeg_available": True,
            "ffprobe_available": True,
            "workdir_writable": True,
            "report_dir_writable": True,
            "windows_path_safe": True,
        }
    )


def _metadata() -> dict[str, Any]:
    return {
        "title": "Owned test",
        "duration": 12.5,
        "uploader": "Owner",
        "channel": "Owner channel",
        "live_status": "not_live",
        "availability": "public",
        "age_limit": 0,
        "formats_available_count": 3,
    }


def _record(
    *,
    status: LinkDownloadStatus = LinkDownloadStatus.VALIDATED,
    error: dict[str, Any] | None = None,
    upload: UploadRecord | None = None,
    probe: dict[str, Any] | None = None,
) -> LinkDownloadRecord:
    return LinkDownloadRecord(
        id="ing_test",
        status=status,
        url="https://www.youtube.com/watch?v=Owned01",
        original_url="https://youtu.be/Owned01",
        reason=error.get("user_message") if error else None,
        upload=upload,
        mode="download_only",
        video_metadata=_metadata() if status is not LinkDownloadStatus.FAILED else {},
        download_selection={"selected_resolution": "1920x1080"},
        link_ingestion_status={
            "current_stage": "validated",
            "progress_percent": 100.0,
        },
        media_probe=probe,
        error=error,
    )


@pytest.mark.parametrize(
    ("url", "source_type"),
    [
        ("https://youtu.be/Owned01", "short_url"),
        ("https://www.youtube.com/watch?v=Owned01", "watch"),
        ("https://www.youtube.com/shorts/Owned01", "shorts"),
    ],
)
def test_url_validation_accepts_supported_youtube_variants(
    url: str,
    source_type: str,
) -> None:
    report = _report()

    issue = validator.validate_url(report, url)

    assert issue is None
    result = validator._summary(report)["url_validation"]
    assert result["passed"] is True
    assert result["source_type"] == source_type
    assert result["canonical_url"] == "https://www.youtube.com/watch?v=Owned01"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("not-a-url", "URL_INVALID"),
        ("https://example.com/watch?v=Owned01", "UNSUPPORTED_SOURCE"),
        ("https://www.youtube.com/playlist?list=PL123", "UNSUPPORTED_SOURCE"),
    ],
)
def test_url_validation_rejects_invalid_or_unsupported_sources(
    url: str,
    code: str,
) -> None:
    issue = validator.validate_url(_report(), url)

    assert issue is not None
    assert issue.code == code


def test_winerror_10061_maps_to_local_backend_unavailable() -> None:
    error = ConnectionRefusedError(10061, "target machine actively refused it")

    issue = validator.classify_exception(error, "backend", _report(execution="api"))

    assert issue.code == "LOCAL_BACKEND_UNAVAILABLE"
    assert "uvicorn" in issue.command_to_try


def test_metadata_and_ffprobe_failures_have_distinct_codes() -> None:
    metadata = validator.classify_exception(
        RuntimeError("YouTube request failed"),
        "metadata",
        _report(),
    )
    probe = validator.classify_exception(
        RuntimeError("invalid data"),
        "ffprobe",
        _report(mode="download_only"),
    )

    assert metadata.code == "YTDLP_METADATA_FAILED"
    assert probe.code == "FFPROBE_FAILED"


def test_pipeline_timeout_has_actionable_taxonomy() -> None:
    issue = validator.classify_exception(
        TimeoutError("timed out"),
        "pipeline",
        _report(mode="full_pipeline", execution="api"),
    )

    assert issue.code == "PIPELINE_TIMEOUT"
    assert issue.command_to_try


def test_backend_health_maps_refused_connection_without_network_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(_url: str, _timeout: float) -> None:
        raise validator.BackendConnectionError(
            "http://127.0.0.1:8000",
            OSError(10061, "actively refused"),
        )

    monkeypatch.setattr(validator, "_tcp_check", refused)
    report = _report(execution="api")

    issue = validator.check_backend_health(
        report,
        backend_url="http://127.0.0.1:8000",
    )

    assert issue is not None
    assert issue.code == "LOCAL_BACKEND_UNAVAILABLE"
    assert "NETWORK_UNAVAILABLE" not in issue.message


def test_backend_health_detects_missing_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validator, "_tcp_check", lambda *_args: None)

    def fake_request(
        _base: str,
        _method: str,
        path: str,
        _payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        del timeout_seconds
        if path == "/api/v1/health/live":
            return {"status": "ok"}
        return {"paths": {"/api/v1/projects/from-link": {"post": {}}}}

    monkeypatch.setattr(validator, "_request_json", fake_request)

    issue = validator.check_backend_health(
        _report(execution="api"),
        backend_url="http://127.0.0.1:8000",
    )

    assert issue is not None
    assert issue.code == "API_ROUTE_UNAVAILABLE"


def test_backend_health_maps_missing_openapi_to_route_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validator, "_tcp_check", lambda *_args: None)

    def fake_request(
        _base: str,
        _method: str,
        path: str,
        _payload: dict[str, Any] | None = None,
        *,
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        del timeout_seconds
        if path == "/api/v1/health/live":
            return {"status": "ok"}
        raise validator.HttpStatusError(404, path, "not found")

    monkeypatch.setattr(validator, "_request_json", fake_request)

    issue = validator.check_backend_health(
        _report(execution="api"),
        backend_url="http://127.0.0.1:8000",
    )

    assert issue is not None
    assert issue.code == "API_ROUTE_UNAVAILABLE"


def test_self_check_reports_missing_ytdlp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    report = _report(mode="self_check", execution="none", rights=False)
    _environment_ready(report)
    validator._summary(report)["environment"]["ytdlp_installed"] = False

    monkeypatch.setattr(
        validator,
        "check_environment",
        lambda *_args, **_kwargs: validator._summary(report)["environment"],
    )
    monkeypatch.setattr(validator, "check_backend_health", lambda *_args, **_kwargs: None)

    validator.run_self_check(
        report,
        backend_url="http://127.0.0.1:8000",
        report_dir=tmp_path,
    )

    result = validator._summary(report)["result"]
    assert result["passed"] is False
    assert result["error_code"] == "YTDLP_NOT_INSTALLED"


def test_self_check_backend_down_is_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="self_check", execution="none", rights=False)
    _environment_ready(report)
    monkeypatch.setattr(
        validator,
        "check_environment",
        lambda *_args, **_kwargs: validator._summary(report)["environment"],
    )
    backend_issue = validator._issue(
        "LOCAL_BACKEND_UNAVAILABLE",
        "Backend is down.",
        report,
    )
    monkeypatch.setattr(
        validator,
        "check_backend_health",
        lambda *_args, **_kwargs: backend_issue,
    )

    validator.run_self_check(
        report,
        backend_url="http://127.0.0.1:8000",
        report_dir=tmp_path,
    )

    result = validator._summary(report)["result"]
    assert result["passed"] is True
    assert result["status"] == "WARNING"
    assert "uvicorn" in result["command_to_try"]


def test_self_check_surfaces_unwritable_workdir_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="self_check", execution="none", rights=False)
    _environment_ready(report)
    environment = validator._summary(report)["environment"]
    environment["workdir_writable"] = False
    environment["warnings"] = ["Work directory is not writable: denied"]
    monkeypatch.setattr(
        validator,
        "check_environment",
        lambda *_args, **_kwargs: environment,
    )
    monkeypatch.setattr(validator, "check_backend_health", lambda *_args, **_kwargs: None)

    validator.run_self_check(
        report,
        backend_url="http://127.0.0.1:8000",
        report_dir=tmp_path,
    )

    assert validator._summary(report)["result"]["passed"] is False
    assert "not writable" in environment["warnings"][0]


@pytest.mark.asyncio
async def test_direct_metadata_uses_service_without_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report()
    _environment_ready(report)

    class FakeService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def prepare(self, *_args: object, **_kwargs: object) -> LinkDownloadRecord:
            return _record()

    monkeypatch.setattr(validator, "VideoLinkIntakeService", FakeService)
    monkeypatch.setattr(
        validator,
        "check_backend_health",
        lambda *_args, **_kwargs: pytest.fail("direct mode called backend"),
    )

    await validator.run_direct_validation(
        report,
        url="https://youtu.be/Owned01",
        mode="metadata_only",
        report_dir=tmp_path,
        timeout_seconds=10,
        poll_interval_seconds=0.01,
        keep_download=False,
        cleanup=True,
    )

    summary = validator._summary(report)
    assert summary["metadata"]["passed"] is True
    assert summary["metadata"]["title"] == "Owned test"
    assert summary["result"]["passed"] is True
    assert summary["api"]["attempted"] is False


@pytest.mark.asyncio
async def test_direct_metadata_failure_uses_ytdlp_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report()
    _environment_ready(report)

    class FakeService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def prepare(self, *_args: object, **_kwargs: object) -> LinkDownloadRecord:
            return _record(
                status=LinkDownloadStatus.FAILED,
                error={
                    "code": "METADATA_EXTRACTION_FAILED",
                    "user_message": "Could not read metadata.",
                    "stage": "metadata_extracting",
                },
            )

    monkeypatch.setattr(validator, "VideoLinkIntakeService", FakeService)

    await validator.run_direct_validation(
        report,
        url="https://youtu.be/Owned01",
        mode="metadata_only",
        report_dir=tmp_path,
        timeout_seconds=10,
        poll_interval_seconds=0.01,
        keep_download=False,
        cleanup=True,
    )

    assert validator._summary(report)["result"]["error_code"] == "YTDLP_METADATA_FAILED"


@pytest.mark.asyncio
async def test_no_cleanup_preserves_isolated_direct_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report()
    _environment_ready(report)

    class FakeService:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def prepare(self, *_args: object, **_kwargs: object) -> LinkDownloadRecord:
            return _record()

    monkeypatch.setattr(validator, "VideoLinkIntakeService", FakeService)

    await validator.run_direct_validation(
        report,
        url="https://youtu.be/Owned01",
        mode="metadata_only",
        report_dir=tmp_path,
        timeout_seconds=10,
        poll_interval_seconds=0.01,
        keep_download=False,
        cleanup=False,
    )

    work_roots = list((tmp_path / ".direct_work").glob("direct_*"))
    assert work_roots
    assert validator._summary(report)["download"]["cleaned_up"] is False


@pytest.mark.asyncio
async def test_direct_download_probes_and_cleans_isolated_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="download_only")
    _environment_ready(report)
    probe = {
        "passed": True,
        "container_duration": 12.5,
        "width": 1920,
        "height": 1080,
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_sample_rate": 48000,
        "has_video": True,
        "has_audio": True,
        "errors": [],
    }

    class FakeService:
        def __init__(self, storage: Any, **_kwargs: object) -> None:
            self.storage = storage

        async def prepare(self, *_args: object, **_kwargs: object) -> LinkDownloadRecord:
            return _record()

        async def get(self, _ingestion_id: str) -> LinkDownloadRecord:
            return _record()

        async def ingest_prepared(self, _ingestion_id: str) -> LinkDownloadRecord:
            upload = UploadRecord(
                id="upl_test",
                filename="owned.mp4",
                content_type="video/mp4",
                size_bytes=5,
                storage_key="uploads/upl_test/source.mp4",
                video_format="mp4",
            )
            await self.storage.put(upload.storage_key, b"video")
            return _record(
                status=LinkDownloadStatus.DOWNLOADED,
                upload=upload,
                probe=probe,
            )

    monkeypatch.setattr(validator, "VideoLinkIntakeService", FakeService)

    await validator.run_direct_validation(
        report,
        url="https://youtu.be/Owned01",
        mode="download_only",
        report_dir=tmp_path,
        timeout_seconds=10,
        poll_interval_seconds=0.01,
        keep_download=False,
        cleanup=True,
    )

    summary = validator._summary(report)
    assert summary["download"]["completed"] is True
    assert summary["download"]["cleaned_up"] is True
    assert summary["download"]["file_path"] is None
    assert summary["ffprobe"]["passed"] is True
    assert summary["result"]["passed"] is True


@pytest.mark.asyncio
async def test_direct_download_keep_copies_only_validated_media(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="download_only")
    _environment_ready(report)

    class FakeService:
        def __init__(self, storage: Any, **_kwargs: object) -> None:
            self.storage = storage

        async def prepare(self, *_args: object, **_kwargs: object) -> LinkDownloadRecord:
            return _record()

        async def get(self, _ingestion_id: str) -> LinkDownloadRecord:
            return _record()

        async def ingest_prepared(self, _ingestion_id: str) -> LinkDownloadRecord:
            upload = UploadRecord(
                id="upl_test",
                filename="owned.mp4",
                content_type="video/mp4",
                size_bytes=5,
                storage_key="uploads/upl_test/source.mp4",
                video_format="mp4",
            )
            await self.storage.put(upload.storage_key, b"video")
            return _record(
                status=LinkDownloadStatus.DOWNLOADED,
                upload=upload,
                probe={
                    "passed": True,
                    "container_duration": 12.5,
                    "width": 1920,
                    "height": 1080,
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "audio_sample_rate": 48000,
                    "has_video": True,
                    "has_audio": True,
                },
            )

    monkeypatch.setattr(validator, "VideoLinkIntakeService", FakeService)

    await validator.run_direct_validation(
        report,
        url="https://youtu.be/Owned01",
        mode="download_only",
        report_dir=tmp_path,
        timeout_seconds=10,
        poll_interval_seconds=0.01,
        keep_download=True,
        cleanup=True,
    )

    download = validator._summary(report)["download"]
    assert download["kept"] is True
    assert Path(download["file_path"]).read_bytes() == b"video"
    assert download["cleaned_up"] is True


@pytest.mark.asyncio
async def test_direct_download_reports_ffprobe_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="download_only")
    _environment_ready(report)

    class FakeService:
        def __init__(self, storage: Any, **_kwargs: object) -> None:
            self.storage = storage

        async def prepare(self, *_args: object, **_kwargs: object) -> LinkDownloadRecord:
            return _record()

        async def get(self, _ingestion_id: str) -> LinkDownloadRecord:
            return _record()

        async def ingest_prepared(self, _ingestion_id: str) -> LinkDownloadRecord:
            upload = UploadRecord(
                id="upl_test",
                filename="owned.mp4",
                content_type="video/mp4",
                size_bytes=5,
                storage_key="uploads/upl_test/source.mp4",
                video_format="mp4",
            )
            await self.storage.put(upload.storage_key, b"video")
            return _record(
                status=LinkDownloadStatus.DOWNLOADED,
                upload=upload,
                probe={"passed": False, "errors": ["invalid data"]},
            )

    monkeypatch.setattr(validator, "VideoLinkIntakeService", FakeService)

    await validator.run_direct_validation(
        report,
        url="https://youtu.be/Owned01",
        mode="download_only",
        report_dir=tmp_path,
        timeout_seconds=10,
        poll_interval_seconds=0.01,
        keep_download=False,
        cleanup=True,
    )

    assert validator._summary(report)["result"]["error_code"] == "FFPROBE_FAILED"


def test_api_mode_stops_before_request_when_backend_is_down(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(execution="api")
    issue = validator._issue(
        "LOCAL_BACKEND_UNAVAILABLE",
        "Backend unavailable.",
        report,
    )
    monkeypatch.setattr(
        validator,
        "check_backend_health",
        lambda *_args, **_kwargs: issue,
    )
    monkeypatch.setattr(
        validator,
        "_request_json",
        lambda *_args, **_kwargs: pytest.fail("API request ran after failed health check"),
    )

    validator.run_api_validation(
        report,
        backend_url="http://127.0.0.1:8000",
        url="https://youtu.be/Owned01",
        mode="metadata_only",
        timeout_seconds=1,
        poll_interval_seconds=0.01,
        report_dir=tmp_path,
    )

    assert validator._summary(report)["result"]["error_code"] == "LOCAL_BACKEND_UNAVAILABLE"


def test_api_metadata_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    report = _report(execution="api")
    monkeypatch.setattr(
        validator,
        "check_backend_health",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        validator,
        "_request_json",
        lambda *_args, **_kwargs: {
            "download": {
                "ingestion_id": "ing_test",
                "status": "validated",
                "video_metadata": _metadata(),
                "download_selection": {"selected_resolution": "1920x1080"},
                "link_ingestion_status": {"current_stage": "validated"},
                "warnings": [],
                "error": None,
            },
            "project": None,
        },
    )

    validator.run_api_validation(
        report,
        backend_url="http://127.0.0.1:8000",
        url="https://youtu.be/Owned01",
        mode="metadata_only",
        timeout_seconds=1,
        poll_interval_seconds=0.01,
        report_dir=tmp_path,
    )

    summary = validator._summary(report)
    assert summary["metadata"]["passed"] is True
    assert summary["api"]["ingestion_id"] == "ing_test"
    assert summary["result"]["passed"] is True


def test_api_ingestion_failure_preserves_specific_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="download_only", execution="api")
    monkeypatch.setattr(
        validator,
        "check_backend_health",
        lambda *_args, **_kwargs: None,
    )
    calls = 0

    def fake_request(*_args: object, **_kwargs: object) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "download": {
                    "ingestion_id": "ing_test",
                    "status": "validated",
                    "video_metadata": _metadata(),
                    "download_selection": {},
                    "link_ingestion_status": {"current_stage": "validated"},
                    "error": None,
                }
            }
        return {
            "download": {
                "ingestion_id": "ing_test",
                "status": "failed",
                "link_ingestion_status": {"current_stage": "downloading"},
                "error": {
                    "code": "FILE_TOO_LARGE",
                    "user_message": "Too large.",
                    "stage": "downloading",
                },
            }
        }

    monkeypatch.setattr(validator, "_request_json", fake_request)

    validator.run_api_validation(
        report,
        backend_url="http://127.0.0.1:8000",
        url="https://youtu.be/Owned01",
        mode="download_only",
        timeout_seconds=1,
        poll_interval_seconds=0.01,
        report_dir=tmp_path,
    )

    assert validator._summary(report)["result"]["error_code"] == "SIZE_LIMIT_EXCEEDED"


def _full_pipeline_request(
    path: str,
    *,
    renders: list[dict[str, Any]],
) -> dict[str, Any]:
    if path == "/api/v1/projects/from-link":
        return {
            "download": {
                "ingestion_id": "ing_test",
                "status": "validated",
                "video_metadata": _metadata(),
                "download_selection": {},
                "link_ingestion_status": {"current_stage": "validated"},
                "error": None,
            }
        }
    if "link-ingestions" in path:
        return {
            "download": {
                "ingestion_id": "ing_test",
                "status": "downloaded",
                "storage_key": "uploads/upl_test/source.mp4",
                "size_bytes": 5,
                "video_metadata": _metadata(),
                "download_selection": {},
                "link_ingestion_status": {"current_stage": "processing_started"},
                "media_probe": {
                    "passed": True,
                    "container_duration": 12.5,
                    "width": 1920,
                    "height": 1080,
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "has_video": True,
                    "has_audio": True,
                },
                "error": None,
            },
            "project": {"id": "prj_test", "status": "analyzing"},
        }
    if path.endswith("/workflow"):
        raise validator.HttpStatusError(404, path, "not found")
    if path.endswith("/rendering/manifest"):
        return {"manifest": {"status": "completed", "renders": renders}}
    if path.endswith("/rendering"):
        return {"status": "completed"}
    if path.endswith("/projects/prj_test"):
        return {"id": "prj_test", "status": "complete"}
    raise AssertionError(path)


def test_full_pipeline_reports_zero_rendered_clips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="full_pipeline", execution="api")
    monkeypatch.setattr(
        validator,
        "check_backend_health",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        validator,
        "_local_api_storage_path",
        lambda *_args, **_kwargs: (True, tmp_path / "source.mp4", None),
    )
    monkeypatch.setattr(
        validator,
        "_request_json",
        lambda _base, _method, path, *_args, **_kwargs: _full_pipeline_request(
            path,
            renders=[],
        ),
    )

    validator.run_api_validation(
        report,
        backend_url="http://127.0.0.1:8000",
        url="https://youtu.be/Owned01",
        mode="full_pipeline",
        timeout_seconds=1,
        poll_interval_seconds=0.01,
        report_dir=tmp_path,
    )

    summary = validator._summary(report)
    assert summary["api"]["project_id"] == "prj_test"
    assert summary["api"]["pipeline_started"] is True
    assert summary["result"]["error_code"] == "NO_CLIPS_RENDERED"


def test_full_pipeline_preserves_project_and_validates_frontend_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="full_pipeline", execution="api")
    renders = [{"clip_id": "clip_test", "metadata": {"sync_validation": {"passed": True}}}]
    monkeypatch.setattr(
        validator,
        "check_backend_health",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        validator,
        "_local_api_storage_path",
        lambda *_args, **_kwargs: (True, tmp_path / "source.mp4", None),
    )
    monkeypatch.setattr(
        validator,
        "_request_json",
        lambda _base, _method, path, *_args, **_kwargs: _full_pipeline_request(
            path,
            renders=renders,
        ),
    )
    monkeypatch.setattr(
        validator,
        "validate_rendered_clips",
        lambda *_args, **_kwargs: None,
    )

    validator.run_api_validation(
        report,
        backend_url="http://127.0.0.1:8000",
        url="https://youtu.be/Owned01",
        mode="full_pipeline",
        timeout_seconds=1,
        poll_interval_seconds=0.01,
        report_dir=tmp_path,
    )

    summary = validator._summary(report)
    assert summary["api"]["project_id"] == "prj_test"
    assert summary["api"]["clips_rendered"] == 1
    assert summary["api"]["frontend_payload_passed"] is True
    assert summary["result"]["passed"] is True


def test_clip_validation_rejects_bad_resolution_and_sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    report = _report(mode="full_pipeline", execution="api")

    def fake_download(
        _base: str,
        _path: str,
        destination: Path,
        *,
        timeout_seconds: float,
    ) -> int:
        del timeout_seconds
        destination.write_bytes(b"render")
        return 6

    monkeypatch.setattr(validator, "_request_file", fake_download)
    monkeypatch.setattr(
        validator,
        "_probe_file",
        lambda _path: {
            "passed": True,
            "container_duration": 8.0,
            "audio_video_delta": 0.3,
            "width": 720,
            "height": 1280,
            "video_codec": "h264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "errors": [],
        },
    )

    issue = validator.validate_rendered_clips(
        report,
        backend_url="http://127.0.0.1:8000",
        project_id="prj_test",
        renders=[{"clip_id": "clip_test", "metadata": {}}],
        report_dir=tmp_path,
        timeout_seconds=10,
    )

    assert issue is not None
    assert issue.code == "CLIP_VALIDATION_FAILED"
    clip = validator._summary(report)["clips"][0]
    assert clip["passed"] is False
    assert any("1080x1920" in warning for warning in clip["warnings"])


def test_reports_write_json_markdown_and_next_command(tmp_path: Path) -> None:
    report = _report(execution="api")
    issue = validator._issue(
        "LOCAL_BACKEND_UNAVAILABLE",
        "Backend unavailable.",
        report,
    )
    validator._set_failure(report, issue, failed_step="backend_health")

    paths = validator.write_reports(report, tmp_path)

    parsed = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["markdown"]).read_text(encoding="utf-8")
    summary = parsed["link_ingestion_validation_v2"]
    result = summary["result"]
    assert result["command_to_try"]
    assert summary["report_files"] == paths
    assert "LOCAL_BACKEND_UNAVAILABLE" in markdown
    assert "uvicorn" in markdown


def test_main_blocks_missing_rights_and_still_writes_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        validator,
        "check_environment",
        lambda report, **_kwargs: validator._summary(report)["environment"],
    )
    monkeypatch.setattr(validator, "validate_url", lambda *_args, **_kwargs: None)

    exit_code = validator.main(
        [
            "--url",
            "https://youtu.be/Owned01",
            "--download-only",
            "--direct",
            "--report-dir",
            str(tmp_path),
        ]
    )

    payload = json.loads((tmp_path / validator.REPORT_JSON_NAME).read_text(encoding="utf-8"))
    assert exit_code == 1
    assert (
        payload["link_ingestion_validation_v2"]["result"]["error_code"]
        == "RIGHTS_CONFIRMATION_REQUIRED"
    )
