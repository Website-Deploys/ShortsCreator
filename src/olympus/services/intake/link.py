"""Safe, progress-aware video-link intake for Olympus V2.

The service accepts only explicitly supported public video URLs, extracts
metadata before download, persists honest progress, validates the downloaded
media with FFprobe, and stores successful files in the normal upload namespace.
It never supplies cookies, credentials, or DRM/login bypass options to yt-dlp.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlparse

from olympus.domain.contracts.storage import StoragePort
from olympus.platform.config.settings import LinkIngestionSettings
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.rendering.command import build_ffprobe_command
from olympus.services.intake.service import ALLOWED_VIDEO_EXTENSIONS, UploadRecord
from olympus.utils import new_id, utc_now

log = get_logger(__name__)

_YOUTUBE_HOSTS = frozenset(
    {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
)
_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_STATUS_CONTENT_TYPE = "application/json"


class LinkDownloadStatus(StrEnum):
    """Top-level status values exposed to API and CLI consumers."""

    QUEUED = "queued"
    METADATA_EXTRACTING = "metadata_extracting"
    VALIDATED = "validated"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class LinkIngestionMode(StrEnum):
    """Supported validation-tool and application execution modes."""

    METADATA_ONLY = "metadata_only"
    DOWNLOAD_ONLY = "download_only"
    FULL_PIPELINE = "full_pipeline"


@dataclass(slots=True)
class DownloadedFile:
    """A local file and sanitized extractor result produced by a downloader."""

    path: Path
    filename: str
    content_type: str | None = None
    info: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LinkDownloadRecord:
    """Persisted truth for one link-ingestion attempt."""

    id: str
    status: LinkDownloadStatus
    url: str
    original_url: str
    reason: str | None = None
    upload: UploadRecord | None = None
    project_id: str | None = None
    job_id: str | None = None
    start_processing: bool = True
    mode: str = LinkIngestionMode.FULL_PIPELINE.value
    requested_quality: str = "best"
    link_source: dict[str, Any] = field(default_factory=dict)
    video_metadata: dict[str, Any] = field(default_factory=dict)
    download_selection: dict[str, Any] = field(default_factory=dict)
    link_ingestion_status: dict[str, Any] = field(default_factory=dict)
    rights_confirmation: dict[str, Any] = field(default_factory=dict)
    media_probe: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = field(default_factory=lambda: utc_now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for storage and API schemas."""

        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LinkDownloadRecord:
        """Load a persisted record while tolerating optional older fields."""

        upload_data = data.get("upload")
        upload = UploadRecord(**upload_data) if isinstance(upload_data, dict) else None
        try:
            status = LinkDownloadStatus(str(data.get("status", LinkDownloadStatus.FAILED.value)))
        except ValueError:
            status = LinkDownloadStatus.FAILED
        return cls(
            id=str(data["id"]),
            status=status,
            url=str(data.get("url") or ""),
            original_url=str(data.get("original_url") or data.get("url") or ""),
            reason=_optional_text(data.get("reason")),
            upload=upload,
            project_id=_optional_text(data.get("project_id")),
            job_id=_optional_text(data.get("job_id")),
            start_processing=bool(data.get("start_processing", True)),
            mode=str(data.get("mode") or LinkIngestionMode.FULL_PIPELINE.value),
            requested_quality=str(data.get("requested_quality") or "best"),
            link_source=_dict(data.get("link_source")),
            video_metadata=_dict(data.get("video_metadata")),
            download_selection=_dict(data.get("download_selection")),
            link_ingestion_status=_dict(data.get("link_ingestion_status")),
            rights_confirmation=_dict(data.get("rights_confirmation")),
            media_probe=_dict(data.get("media_probe")) or None,
            error=_dict(data.get("error")) or None,
            warnings=[str(item) for item in _list(data.get("warnings"))],
            created_at=str(data.get("created_at") or utc_now().isoformat()),
            updated_at=str(data.get("updated_at") or utc_now().isoformat()),
        )


class LinkIngestionError(RuntimeError):
    """Expected ingestion failure with a stable user-facing contract."""

    def __init__(
        self,
        code: str,
        user_message: str,
        *,
        developer_message: str | None = None,
        retryable: bool = False,
        stage: str,
        suggestion: str,
    ) -> None:
        self.code = code
        self.user_message = user_message
        self.developer_message = developer_message or user_message
        self.retryable = retryable
        self.stage = stage
        self.suggestion = suggestion
        super().__init__(self.developer_message)

    def to_dict(self) -> dict[str, Any]:
        """Return the structured error payload persisted with the record."""

        return {
            "code": self.code,
            "user_message": self.user_message,
            "developer_message": self.developer_message,
            "retryable": self.retryable,
            "stage": self.stage,
            "suggestion": self.suggestion,
        }


LinkIngestionFailure = LinkIngestionError


Downloader = Callable[[str, Path], DownloadedFile]
MetadataExtractor = Callable[[str], dict[str, Any]]
MediaProbe = Callable[[Path], dict[str, Any]]
ProgressHook = Callable[[dict[str, Any]], None]


class VideoLinkIntakeService:
    """Validate, inspect, download, probe, and store supported video links."""

    def __init__(
        self,
        storage: StoragePort,
        downloader: Downloader | None = None,
        *,
        metadata_extractor: MetadataExtractor | None = None,
        media_probe: MediaProbe | None = None,
        settings: LinkIngestionSettings | None = None,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
    ) -> None:
        self._storage = storage
        self._custom_downloader = downloader
        self._metadata_extractor = metadata_extractor or self._extract_metadata_with_ytdlp
        self._media_probe = media_probe or self._probe_with_ffprobe
        self._settings = settings or LinkIngestionSettings()
        self._ffmpeg_binary = ffmpeg_binary
        self._ffprobe_binary = ffprobe_binary

    async def prepare(
        self,
        url: str,
        *,
        permission_confirmed: bool,
        start_processing: bool = True,
        mode: LinkIngestionMode | str = LinkIngestionMode.FULL_PIPELINE,
        quality: str = "best",
    ) -> LinkDownloadRecord:
        """Validate a URL, persist an ingestion id, and extract safe metadata."""

        if not self._settings.enabled:
            raise ValidationError(
                "Video-link ingestion is disabled.",
                code="LINK_INGESTION_DISABLED",
            )
        if quality != "best":
            raise ValidationError(
                "Only the safe 'best' quality policy is currently supported.",
                code="UNSUPPORTED_QUALITY",
            )
        try:
            normalized_mode = LinkIngestionMode(str(mode))
        except ValueError as exc:
            raise ValidationError(
                "Unknown link-ingestion mode.",
                code="INVALID_INGESTION_MODE",
            ) from exc

        source = self.validate_url(url, permission_confirmed=permission_confirmed)
        now = utc_now().isoformat()
        record = LinkDownloadRecord(
            id=new_id("ing"),
            status=LinkDownloadStatus.METADATA_EXTRACTING,
            url=str(source["normalized_url"]),
            original_url=str(source["original_url"]),
            start_processing=start_processing,
            mode=normalized_mode.value,
            requested_quality=quality,
            link_source=source,
            rights_confirmation={
                "confirmed": permission_confirmed,
                "confirmed_at": now if permission_confirmed else None,
                "source": "link_ingestion_form",
            },
            link_ingestion_status=_status_payload("metadata_extracting", started_at=now),
            created_at=now,
            updated_at=now,
        )
        await self._save(record)

        try:
            raw_info = await asyncio.wait_for(
                asyncio.to_thread(self._metadata_extractor, record.url),
                timeout=self._settings.metadata_timeout_seconds,
            )
            metadata = self._metadata_from_info(raw_info, record)
            self._validate_metadata(metadata, record)
            selection = self._select_download(raw_info, quality=quality)
        except ImportError as exc:
            return await self._fail(
                record,
                LinkIngestionFailure(
                    "DOWNLOADER_UNAVAILABLE",
                    "Video-link ingestion is unavailable because yt-dlp is not installed.",
                    developer_message=str(exc),
                    stage="metadata_extracting",
                    suggestion=(
                        'Install the optional dependency with `pip install -e ".[video-links]`.'
                    ),
                ),
                unavailable=True,
            )
        except TimeoutError as exc:
            return await self._fail(
                record,
                LinkIngestionFailure(
                    "METADATA_EXTRACTION_FAILED",
                    "Olympus timed out while reading video metadata.",
                    developer_message=str(exc),
                    retryable=True,
                    stage="metadata_extracting",
                    suggestion="Check the network connection and try again.",
                ),
            )
        except LinkIngestionFailure as exc:
            return await self._fail(record, exc)
        except Exception as exc:
            return await self._fail(record, _classify_exception(exc, "metadata_extracting"))

        record.video_metadata = metadata
        record.download_selection = selection
        record.status = LinkDownloadStatus.VALIDATED
        record.link_ingestion_status = _status_payload(
            "validated",
            started_at=record.link_ingestion_status.get("started_at"),
        )
        await self._save(record)
        return record

    async def ingest(
        self,
        url: str,
        *,
        permission_confirmed: bool,
    ) -> LinkDownloadRecord:
        """Compatibility helper that prepares and downloads in one await."""

        record = await self.prepare(
            url,
            permission_confirmed=permission_confirmed,
            start_processing=False,
            mode=LinkIngestionMode.DOWNLOAD_ONLY,
        )
        if record.status is not LinkDownloadStatus.VALIDATED:
            return record
        return await self.ingest_prepared(record.id)

    async def ingest_prepared(self, ingestion_id: str) -> LinkDownloadRecord:
        """Download, probe, and store a previously validated ingestion record."""

        record = await self.get(ingestion_id)
        if record.status is not LinkDownloadStatus.VALIDATED:
            return record
        if record.mode == LinkIngestionMode.METADATA_ONLY.value:
            return record

        record.status = LinkDownloadStatus.DOWNLOADING
        record.link_ingestion_status = _status_payload(
            "downloading",
            progress_percent=0.0,
            started_at=record.link_ingestion_status.get("started_at") or utc_now().isoformat(),
        )
        await self._save(record)

        directory = Path(tempfile.mkdtemp(prefix="olympus_link_"))
        loop = asyncio.get_running_loop()
        download_started = time.monotonic()
        last_reported = 0.0
        max_bytes = self._settings.max_source_file_size_mb * 1024 * 1024

        def progress_hook(payload: dict[str, Any]) -> None:
            nonlocal last_reported
            elapsed = time.monotonic() - download_started
            if elapsed > self._settings.download_timeout_seconds:
                raise RuntimeError(
                    f"DOWNLOAD_TIMEOUT: exceeded {self._settings.download_timeout_seconds}s"
                )
            total = _as_int(payload.get("total_bytes")) or _as_int(
                payload.get("total_bytes_estimate")
            )
            downloaded = _as_int(payload.get("downloaded_bytes")) or 0
            if total is not None and total > max_bytes:
                raise RuntimeError(f"FILE_TOO_LARGE: estimated size is {total} bytes")
            if downloaded > max_bytes:
                raise RuntimeError(f"FILE_TOO_LARGE: downloaded size exceeded {max_bytes} bytes")
            now = time.monotonic()
            if (
                payload.get("status") != "finished"
                and now - last_reported < self._settings.report_progress_interval_seconds
            ):
                return
            last_reported = now
            future = asyncio.run_coroutine_threadsafe(
                self._persist_progress(ingestion_id, payload),
                loop,
            )
            try:
                future.result(timeout=10)
            except Exception as exc:
                log.warning(
                    "link_progress_persist_failed",
                    ingestion_id=ingestion_id,
                    error=str(exc),
                )

        try:
            if self._custom_downloader is None:
                downloaded = await asyncio.to_thread(
                    self._download_with_ytdlp,
                    record.url,
                    directory,
                    progress_hook,
                )
            else:
                downloaded = await asyncio.to_thread(
                    self._custom_downloader,
                    record.url,
                    directory,
                )
            record = await self.get(ingestion_id)
            self._validate_downloaded_path(downloaded, directory)
            size_bytes = downloaded.path.stat().st_size
            if size_bytes > max_bytes:
                raise LinkIngestionFailure(
                    "FILE_TOO_LARGE",
                    "The downloaded video is larger than the configured limit.",
                    developer_message=f"Downloaded size {size_bytes} exceeds {max_bytes} bytes.",
                    stage="downloading",
                    suggestion="Use a shorter source or increase the configured size limit.",
                )

            record.link_ingestion_status = {
                **record.link_ingestion_status,
                "status": "probing",
                "current_stage": "probing",
                "progress_percent": 100.0,
            }
            await self._save(record)
            probe = await asyncio.to_thread(self._media_probe, downloaded.path)
            if not probe.get("passed"):
                errors = "; ".join(str(item) for item in _list(probe.get("errors")))
                raise LinkIngestionFailure(
                    "FFPROBE_FAILED",
                    "Olympus downloaded the file but could not validate it as usable video.",
                    developer_message=errors or "FFprobe validation did not pass.",
                    stage="probing",
                    suggestion="Upload the source file manually or try another public source.",
                )
            if not probe.get("has_video"):
                raise LinkIngestionFailure(
                    "FFPROBE_FAILED",
                    "The downloaded source does not contain a video stream.",
                    stage="probing",
                    suggestion="Use a link to a normal public video.",
                )

            ext = downloaded.path.suffix.lower()
            upload_id = new_id("upl")
            storage_key = f"uploads/{upload_id}/source{ext}"
            stored = await self._storage.put_stream(
                storage_key,
                _read_file_chunks(downloaded.path),
                content_type=downloaded.content_type or _content_type_for(ext),
            )
            upload = UploadRecord(
                id=upload_id,
                filename=_safe_filename(downloaded.filename),
                content_type=downloaded.content_type or _content_type_for(ext),
                size_bytes=stored.size_bytes,
                storage_key=storage_key,
                video_format=ext.lstrip("."),
            )
            record = await self.get(ingestion_id)
            record.upload = upload
            record.media_probe = probe
            record.download_selection = _actual_selection(
                downloaded.info,
                record.download_selection,
                upload,
            )
            record.status = LinkDownloadStatus.DOWNLOADED
            record.reason = None
            record.error = None
            record.link_ingestion_status = {
                **record.link_ingestion_status,
                "status": "stored",
                "current_stage": "stored",
                "progress_percent": 100.0,
                "downloaded_bytes": stored.size_bytes,
                "total_bytes": stored.size_bytes,
                "ended_at": utc_now().isoformat(),
                "error_code": None,
                "error_message": None,
            }
            await self._save(record)
            log.info(
                "video_link_download_stored",
                ingestion_id=record.id,
                storage_key=storage_key,
                size_bytes=stored.size_bytes,
            )
            return record
        except ImportError as exc:
            return await self._fail(
                record,
                LinkIngestionFailure(
                    "DOWNLOADER_UNAVAILABLE",
                    "Video-link ingestion is unavailable because yt-dlp is not installed.",
                    developer_message=str(exc),
                    stage="downloading",
                    suggestion=(
                        'Install the optional dependency with `pip install -e ".[video-links]`.'
                    ),
                ),
                unavailable=True,
            )
        except LinkIngestionFailure as exc:
            return await self._fail(record, exc)
        except Exception as exc:
            return await self._fail(record, _classify_exception(exc, "downloading"))
        finally:
            if self._settings.cleanup_partial_downloads:
                await asyncio.to_thread(shutil.rmtree, directory, True)

    async def get(self, ingestion_id: str) -> LinkDownloadRecord:
        """Load a persisted ingestion record."""

        key = _record_key(ingestion_id)
        if not await self._storage.exists(key):
            raise NotFoundError(
                "Link ingestion was not found.",
                details={"ingestion_id": ingestion_id},
            )
        raw = await self._storage.get(key)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError(
                "Stored link-ingestion status is invalid.",
                code="INVALID_INGESTION_RECORD",
            ) from exc
        if not isinstance(payload, dict):
            raise ValidationError(
                "Stored link-ingestion status is invalid.",
                code="INVALID_INGESTION_RECORD",
            )
        return LinkDownloadRecord.from_dict(payload)

    async def attach_project(
        self,
        ingestion_id: str,
        project_id: str,
        *,
        processing_started: bool,
        job_id: str | None = None,
    ) -> LinkDownloadRecord:
        """Attach the project created from a stored source and update its stage."""

        record = await self.get(ingestion_id)
        record.project_id = project_id
        if job_id is not None:
            record.job_id = job_id
        stage = "processing_started" if processing_started else "stored"
        record.link_ingestion_status = {
            **record.link_ingestion_status,
            "status": stage,
            "current_stage": stage,
        }
        await self._save(record)
        return record

    async def fail_after_download(
        self,
        ingestion_id: str,
        exc: Exception,
        *,
        stage: str,
        cleanup_upload: bool = True,
    ) -> LinkDownloadRecord:
        """Record a project or pipeline failure and clean its stored upload."""

        record = await self.get(ingestion_id)
        if cleanup_upload and record.upload is not None:
            await self._storage.delete(record.upload.storage_key)
            record.upload = None
        return await self._fail(record, _classify_exception(exc, stage))

    def validate_url(self, url: str, *, permission_confirmed: bool) -> dict[str, Any]:
        """Validate and normalize YouTube watch, short, and share URLs."""

        cleaned = url.strip()
        if self._settings.require_user_rights_confirmation and not permission_confirmed:
            raise ValidationError(
                "Confirm that you own this video, have permission, or are allowed to process it.",
                code="RIGHTS_CONFIRMATION_REQUIRED",
            )
        if not cleaned:
            raise ValidationError("Paste a video link first.", code="INVALID_URL")
        try:
            parsed = urlparse(cleaned)
            port = parsed.port
        except ValueError as exc:
            raise ValidationError("The video link is malformed.", code="INVALID_URL") from exc
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValidationError(
                "Video link must be a valid http(s) URL.",
                code="INVALID_URL",
            )
        if parsed.username or parsed.password or port not in {None, 80, 443}:
            raise ValidationError(
                "Credentials and custom ports are not allowed in video links.",
                code="INVALID_URL",
            )
        host = (parsed.hostname or "").lower().rstrip(".")
        if "youtube" not in self._settings.allowed_platforms_list or host not in _YOUTUBE_HOSTS:
            raise ValidationError(
                "Only public YouTube video and Shorts links are currently supported.",
                code="UNSUPPORTED_PLATFORM",
                details={"host": host or None},
            )

        query = parse_qs(parsed.query, keep_blank_values=True)
        segments = [segment for segment in parsed.path.split("/") if segment]
        video_id: str | None = None
        url_type: str | None = None
        if host in {"youtu.be", "www.youtu.be"} and len(segments) == 1:
            video_id = segments[0]
            url_type = "short_url"
        elif host in _YOUTUBE_HOSTS - {"youtu.be", "www.youtu.be"}:
            if parsed.path.rstrip("/") == "/watch":
                values = query.get("v") or []
                video_id = values[0] if values else None
                url_type = "watch"
            elif len(segments) == 2 and segments[0].lower() == "shorts":
                video_id = segments[1]
                url_type = "shorts"

        if not video_id and query.get("list") and not self._settings.allow_playlists:
            raise ValidationError(
                "Playlist-only links are not supported. Paste a link to one video.",
                code="PLAYLIST_NOT_SUPPORTED",
            )
        if not video_id or not _VIDEO_ID_PATTERN.fullmatch(video_id):
            raise ValidationError(
                "Paste a valid YouTube watch, youtu.be, or Shorts link.",
                code="INVALID_URL",
            )

        normalized_url = f"https://www.youtube.com/watch?v={video_id}"
        warnings: list[str] = []
        if cleaned != normalized_url:
            warnings.append("URL normalized and nonessential query parameters removed.")
        return {
            "original_url": cleaned,
            "normalized_url": normalized_url,
            "platform": "youtube",
            "video_id": video_id,
            "url_type": url_type,
            "validation_status": "validated",
            "validation_warnings": warnings,
        }

    def _validate_url(self, url: str, *, permission_confirmed: bool) -> str:
        """Backward-compatible normalized URL helper."""

        source = self.validate_url(url, permission_confirmed=permission_confirmed)
        return str(source["normalized_url"])

    def _metadata_from_info(
        self,
        info: dict[str, Any],
        record: LinkDownloadRecord,
    ) -> dict[str, Any]:
        entries = _list(info.get("entries"))
        if info.get("_type") in {"playlist", "multi_video"} or entries:
            raise LinkIngestionFailure(
                "PLAYLIST_NOT_SUPPORTED",
                "Playlist links are not supported. Paste a link to one video.",
                stage="metadata_extracting",
                suggestion="Open the individual video and copy its watch URL.",
            )
        formats = [item for item in _list(info.get("formats")) if isinstance(item, dict)]
        description = _optional_text(info.get("description"))
        return {
            "platform": "youtube",
            "video_id": _optional_text(info.get("id")) or record.link_source.get("video_id"),
            "title": _bounded_text(info.get("title"), 300),
            "uploader": _bounded_text(info.get("uploader"), 200),
            "channel": _bounded_text(info.get("channel"), 200),
            "duration": _as_float(info.get("duration")),
            "view_count_if_available": _as_int(info.get("view_count")),
            "upload_date_if_available": _optional_text(info.get("upload_date")),
            "description_excerpt_if_allowed": description[:500] if description else None,
            "thumbnail_url": _optional_text(info.get("thumbnail")),
            "webpage_url": _optional_text(info.get("webpage_url")) or record.url,
            "original_url": record.original_url,
            "availability": _optional_text(info.get("availability")),
            "age_limit": _as_int(info.get("age_limit")),
            "is_live": bool(info.get("is_live")),
            "was_live": bool(info.get("was_live")),
            "live_status": _optional_text(info.get("live_status")),
            "formats_available": [_format_summary(item) for item in formats[:100]],
            "formats_available_count": len(formats),
            "subtitles_available": bool(_dict(info.get("subtitles"))),
            "automatic_captions_available": bool(_dict(info.get("automatic_captions"))),
            "extraction_warnings": [],
        }

    def _validate_metadata(
        self,
        metadata: dict[str, Any],
        record: LinkDownloadRecord,
    ) -> None:
        video_id = str(metadata.get("video_id") or "")
        if video_id != record.link_source.get("video_id"):
            raise LinkIngestionFailure(
                "METADATA_EXTRACTION_FAILED",
                "The resolved video did not match the requested link.",
                developer_message=f"Expected {record.link_source.get('video_id')}, got {video_id}.",
                stage="metadata_extracting",
                suggestion="Copy the canonical YouTube watch URL and try again.",
            )
        webpage_url = _optional_text(metadata.get("webpage_url"))
        if webpage_url:
            try:
                resolved = self.validate_url(webpage_url, permission_confirmed=True)
            except ValidationError as exc:
                raise LinkIngestionFailure(
                    "METADATA_EXTRACTION_FAILED",
                    "The video redirected to an unsupported destination.",
                    developer_message=str(exc),
                    stage="metadata_extracting",
                    suggestion="Use a canonical public YouTube watch URL.",
                ) from exc
            if resolved.get("video_id") != video_id:
                raise LinkIngestionFailure(
                    "METADATA_EXTRACTION_FAILED",
                    "The video redirected to a different source.",
                    stage="metadata_extracting",
                    suggestion="Use a canonical public YouTube watch URL.",
                )

        availability = str(metadata.get("availability") or "").lower()
        if availability in {"private", "premium_only", "subscriber_only"}:
            raise LinkIngestionFailure(
                "PRIVATE_VIDEO",
                "This video is private or restricted. Use a public video you may process.",
                stage="metadata_extracting",
                suggestion="Upload your own source file manually if you have lawful access.",
            )
        if availability in {"needs_auth", "login_required"}:
            raise LinkIngestionFailure(
                "LOGIN_REQUIRED",
                "This video requires login and cannot be ingested.",
                stage="metadata_extracting",
                suggestion="Use a public video or upload the file manually.",
            )
        if (_as_int(metadata.get("age_limit")) or 0) >= 18:
            raise LinkIngestionFailure(
                "LOGIN_REQUIRED",
                "Age-restricted videos are not supported by link ingestion.",
                stage="metadata_extracting",
                suggestion="Upload a source file you are allowed to process manually.",
            )
        is_currently_live = metadata.get("is_live") or metadata.get("live_status") == "is_live"
        if is_currently_live and not self._settings.allow_live_streams:
            raise LinkIngestionFailure(
                "LIVE_STREAM_NOT_SUPPORTED",
                "Live streams are not supported while they are live.",
                stage="metadata_extracting",
                suggestion="Wait for the archived video or upload a finished recording.",
            )
        duration = _as_float(metadata.get("duration"))
        if duration is None or duration <= 0:
            raise LinkIngestionFailure(
                "METADATA_EXTRACTION_FAILED",
                "Olympus could not determine the video duration safely.",
                stage="metadata_extracting",
                suggestion="Use a normal public video or upload the file manually.",
            )
        max_duration = self._settings.max_source_duration_minutes * 60
        if duration > max_duration:
            raise LinkIngestionFailure(
                "VIDEO_TOO_LONG",
                "This video is longer than the configured ingestion limit.",
                developer_message=f"Duration {duration}s exceeds {max_duration}s.",
                stage="metadata_extracting",
                suggestion="Use a shorter video or increase the limit in settings.",
            )
        if not metadata.get("formats_available_count"):
            raise LinkIngestionFailure(
                "METADATA_EXTRACTION_FAILED",
                "No usable public media formats were reported for this video.",
                stage="metadata_extracting",
                suggestion="Try another public video or upload the file manually.",
            )

    def _select_download(self, info: dict[str, Any], *, quality: str) -> dict[str, Any]:
        formats = [item for item in _list(info.get("formats")) if isinstance(item, dict)]
        max_height = self._settings.max_height
        videos = [
            item
            for item in formats
            if str(item.get("vcodec") or "none") != "none"
            and not bool(item.get("has_drm"))
            and (
                (height := _as_int(item.get("height"))) is None
                or height <= max_height
            )
        ]
        if not videos:
            if any(bool(item.get("has_drm")) for item in formats):
                raise LinkIngestionFailure(
                    "DOWNLOAD_FAILED",
                    "This protected video cannot be ingested.",
                    stage="metadata_extracting",
                    suggestion="Use an unprotected source you are allowed to process.",
                )
            raise LinkIngestionFailure(
                "METADATA_EXTRACTION_FAILED",
                "No usable video format exists within the configured quality limit.",
                stage="metadata_extracting",
                suggestion="Increase the maximum height or upload the source file manually.",
            )
        selected_video = max(videos, key=self._video_format_score)
        selected_audio: dict[str, Any] | None = None
        if str(selected_video.get("acodec") or "none") == "none":
            audios = [
                item
                for item in formats
                if str(item.get("vcodec") or "none") == "none"
                and str(item.get("acodec") or "none") != "none"
            ]
            if not audios:
                raise LinkIngestionFailure(
                    "METADATA_EXTRACTION_FAILED",
                    "No usable audio stream was reported for this video.",
                    stage="metadata_extracting",
                    suggestion="Upload the source file manually.",
                )
            selected_audio = max(audios, key=self._audio_format_score)

        estimated = _format_size(selected_video)
        if selected_audio is not None:
            audio_size = _format_size(selected_audio)
            if estimated is not None and audio_size is not None:
                estimated += audio_size
            else:
                estimated = None
        max_bytes = self._settings.max_source_file_size_mb * 1024 * 1024
        if estimated is not None and estimated > max_bytes:
            raise LinkIngestionFailure(
                "FILE_TOO_LARGE",
                "The best safe source format exceeds the configured file-size limit.",
                developer_message=f"Estimated {estimated} bytes exceeds {max_bytes} bytes.",
                stage="metadata_extracting",
                suggestion="Use a shorter source or increase the configured size limit.",
            )

        video_format_id = str(selected_video.get("format_id") or "unknown")
        audio_format_id = str(selected_audio.get("format_id")) if selected_audio else None
        height = _as_int(selected_video.get("height"))
        width = _as_int(selected_video.get("width"))
        ext = str(selected_video.get("ext") or "")
        return {
            "requested_quality": quality,
            "selected_format_id": (
                f"{video_format_id}+{audio_format_id}" if audio_format_id else video_format_id
            ),
            "selected_resolution": (
                f"{width}x{height}" if width is not None and height is not None else None
            ),
            "selected_video_codec": _optional_text(selected_video.get("vcodec")),
            "selected_audio_codec": _optional_text(
                (selected_audio or selected_video).get("acodec")
            ),
            "selected_container": self._settings.preferred_container,
            "estimated_filesize": estimated,
            "fallback_used": height is None or ext != self._settings.preferred_container,
            "selection_reason": (
                f"Best available video at or below {max_height}p, preferring compatible codecs "
                f"and {self._settings.preferred_container} output."
            ),
        }

    def _video_format_score(self, item: dict[str, Any]) -> tuple[int, int, int, float, float]:
        height = _as_int(item.get("height")) or 0
        codec = str(item.get("vcodec") or "").lower()
        ext = str(item.get("ext") or "").lower()
        return (
            height,
            _preference_score(codec, self._settings.preferred_video_codecs_list),
            int(ext == self._settings.preferred_container),
            _as_float(item.get("fps")) or 0.0,
            _as_float(item.get("tbr")) or 0.0,
        )

    def _audio_format_score(self, item: dict[str, Any]) -> tuple[int, int, float]:
        codec = str(item.get("acodec") or "").lower()
        ext = str(item.get("ext") or "").lower()
        return (
            _preference_score(codec, self._settings.preferred_audio_codecs_list),
            int(ext in {"m4a", "mp4"}),
            _as_float(item.get("abr")) or 0.0,
        )

    def _extract_metadata_with_ytdlp(self, url: str) -> dict[str, Any]:
        try:
            from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
        except ModuleNotFoundError as exc:
            raise ImportError("yt-dlp is not installed") from exc

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "skip_download": True,
            "socket_timeout": min(30.0, self._settings.metadata_timeout_seconds),
            "retries": 1,
            "extractor_retries": 1,
            "ignoreconfig": True,
            "cookiefile": None,
            "cookiesfrombrowser": None,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "writethumbnail": False,
        }
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            sanitized = ydl.sanitize_info(info)
        if not isinstance(sanitized, dict):
            raise RuntimeError("yt-dlp did not return a video metadata object.")
        return sanitized

    def _download_with_ytdlp(
        self,
        url: str,
        directory: Path,
        progress_hook: ProgressHook,
    ) -> DownloadedFile:
        try:
            from yt_dlp import YoutubeDL
        except ModuleNotFoundError as exc:
            raise ImportError("yt-dlp is not installed") from exc

        max_height = self._settings.max_height
        format_selector = (
            f"bv[height<=?{max_height}][ext=mp4]+ba[ext=m4a]/"
            f"bv[height<=?{max_height}]+ba/"
            f"b[height<=?{max_height}]"
        )
        options: dict[str, Any] = {
            "format": format_selector,
            "format_sort": [
                f"res:{max_height}",
                "vcodec:h264",
                "acodec:aac",
                "ext:mp4:m4a",
            ],
            "merge_output_format": self._settings.preferred_container,
            "noplaylist": True,
            "outtmpl": str(directory / "source.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "ignoreconfig": True,
            "cookiefile": None,
            "cookiesfrombrowser": None,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "writethumbnail": False,
            "max_filesize": self._settings.max_source_file_size_mb * 1024 * 1024,
            "socket_timeout": min(30.0, self._settings.download_timeout_seconds),
            "retries": 2,
            "fragment_retries": 2,
            "extractor_retries": 1,
            "file_access_retries": 2,
            "concurrent_fragment_downloads": 1,
            "progress_hooks": [progress_hook],
            "overwrites": True,
        }
        if Path(self._ffmpeg_binary).parent != Path("."):
            options["ffmpeg_location"] = self._ffmpeg_binary
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            sanitized = ydl.sanitize_info(info)
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.lower() in ALLOWED_VIDEO_EXTENSIONS
            and not path.name.endswith(".part")
        ]
        if not candidates:
            raise RuntimeError("yt-dlp completed but no supported video file was found.")
        path = max(candidates, key=lambda item: item.stat().st_size)
        title = _bounded_text(sanitized.get("title"), 180) if isinstance(sanitized, dict) else None
        return DownloadedFile(
            path=path,
            filename=_safe_filename(f"{title or 'linked-video'}{path.suffix}"),
            content_type=_content_type_for(path.suffix.lower()),
            info=sanitized if isinstance(sanitized, dict) else {},
        )

    def _probe_with_ffprobe(self, path: Path) -> dict[str, Any]:
        binary = shutil.which(self._ffprobe_binary)
        if binary is None and Path(self._ffprobe_binary).is_file():
            binary = self._ffprobe_binary
        if binary is None:
            return {
                "passed": False,
                "errors": ["ffprobe is not available on the backend process PATH"],
            }
        try:
            completed = subprocess.run(
                build_ffprobe_command(binary=binary, path=str(path)),
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"passed": False, "errors": [str(exc)]}
        if completed.returncode != 0:
            return {
                "passed": False,
                "errors": [completed.stderr.strip() or f"ffprobe exited {completed.returncode}"],
            }
        try:
            raw = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            return {"passed": False, "errors": [f"ffprobe returned invalid JSON: {exc}"]}
        streams = [item for item in _list(raw.get("streams")) if isinstance(item, dict)]
        video = next((item for item in streams if item.get("codec_type") == "video"), {})
        audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
        container = _dict(raw.get("format"))
        duration = _as_float(container.get("duration")) or _as_float(video.get("duration"))
        return {
            "passed": bool(video) and duration is not None and duration > 0,
            "container_duration": duration,
            "width": _as_int(video.get("width")),
            "height": _as_int(video.get("height")),
            "video_codec": _optional_text(video.get("codec_name")),
            "audio_codec": _optional_text(audio.get("codec_name")),
            "audio_sample_rate": _as_int(audio.get("sample_rate")),
            "has_video": bool(video),
            "has_audio": bool(audio),
            "format_name": _optional_text(container.get("format_name")),
            "errors": [],
        }

    def _validate_downloaded_path(self, downloaded: DownloadedFile, directory: Path) -> None:
        try:
            resolved = downloaded.path.resolve(strict=True)
        except OSError as exc:
            raise LinkIngestionFailure(
                "DOWNLOAD_FAILED",
                "The downloader did not produce a usable video file.",
                developer_message=str(exc),
                retryable=True,
                stage="downloading",
                suggestion="Try again or upload the source file manually.",
            ) from exc
        root = directory.resolve()
        if root not in resolved.parents or not resolved.is_file():
            raise LinkIngestionFailure(
                "DOWNLOAD_FAILED",
                "The downloader produced an unsafe output path.",
                stage="downloading",
                suggestion="Upload the source file manually.",
            )
        ext = resolved.suffix.lower()
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise LinkIngestionFailure(
                "DOWNLOAD_FAILED",
                f"Downloaded file format {ext or '<none>'} is not supported.",
                stage="downloading",
                suggestion="Upload an MP4, MOV, AVI, MKV, or WEBM file manually.",
            )
        if resolved.stat().st_size <= 0:
            raise LinkIngestionFailure(
                "DOWNLOAD_FAILED",
                "The downloader produced an empty video file.",
                stage="downloading",
                suggestion="Try again or upload the source file manually.",
            )

    async def _persist_progress(self, ingestion_id: str, payload: dict[str, Any]) -> None:
        record = await self.get(ingestion_id)
        downloaded = _as_int(payload.get("downloaded_bytes")) or 0
        total = _as_int(payload.get("total_bytes")) or _as_int(
            payload.get("total_bytes_estimate")
        )
        percent = round(downloaded / total * 100, 2) if total and total > 0 else None
        stage = "merging" if payload.get("status") == "finished" else "downloading"
        record.status = LinkDownloadStatus.DOWNLOADING
        record.link_ingestion_status = {
            **record.link_ingestion_status,
            "status": stage,
            "current_stage": stage,
            "progress_percent": percent,
            "downloaded_bytes": downloaded,
            "total_bytes": total,
            "speed": _as_float(payload.get("speed")),
            "eta_seconds": _as_float(payload.get("eta")),
        }
        await self._save(record)

    async def _fail(
        self,
        record: LinkDownloadRecord,
        failure: LinkIngestionFailure,
        *,
        unavailable: bool = False,
    ) -> LinkDownloadRecord:
        record.status = (
            LinkDownloadStatus.UNAVAILABLE if unavailable else LinkDownloadStatus.FAILED
        )
        record.reason = failure.user_message
        record.error = failure.to_dict()
        record.link_ingestion_status = {
            **record.link_ingestion_status,
            "status": "failed",
            "current_stage": failure.stage,
            "ended_at": utc_now().isoformat(),
            "error_code": failure.code,
            "error_message": failure.user_message,
        }
        await self._save(record)
        log.warning(
            "video_link_ingestion_failed",
            ingestion_id=record.id,
            code=failure.code,
            stage=failure.stage,
            error=failure.developer_message,
        )
        return record

    async def _save(self, record: LinkDownloadRecord) -> None:
        record.updated_at = utc_now().isoformat()
        payload = json.dumps(record.to_dict(), ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
        await self._storage.put(
            _record_key(record.id),
            payload,
            content_type=_STATUS_CONTENT_TYPE,
        )


async def _read_file_chunks(path: Path, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while True:
            chunk = await asyncio.to_thread(handle.read, chunk_size)
            if not chunk:
                break
            yield chunk


def _record_key(ingestion_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,100}", ingestion_id):
        raise ValidationError("Invalid link-ingestion id.", code="INVALID_INGESTION_ID")
    return f"link_ingestions/{ingestion_id}/status.json"


def _status_payload(
    stage: str,
    *,
    progress_percent: float | None = None,
    started_at: str | None = None,
) -> dict[str, Any]:
    return {
        "status": stage,
        "progress_percent": progress_percent,
        "downloaded_bytes": 0,
        "total_bytes": None,
        "speed": None,
        "eta_seconds": None,
        "current_stage": stage,
        "started_at": started_at or utc_now().isoformat(),
        "ended_at": None,
        "error_code": None,
        "error_message": None,
        "warnings": [],
    }


def _classify_exception(exc: Exception, stage: str) -> LinkIngestionFailure:
    message = str(exc)
    lowered = message.lower()
    if "file_too_large" in lowered or "max-filesize" in lowered:
        return LinkIngestionFailure(
            "FILE_TOO_LARGE",
            "The selected video is larger than the configured limit.",
            developer_message=message,
            stage=stage,
            suggestion="Use a shorter source or increase the configured size limit.",
        )
    if "download_timeout" in lowered or "timed out" in lowered:
        return LinkIngestionFailure(
            "DOWNLOAD_FAILED",
            "The video download timed out.",
            developer_message=message,
            retryable=True,
            stage=stage,
            suggestion="Check the network connection and try again.",
        )
    if "private video" in lowered or "members-only" in lowered:
        return LinkIngestionFailure(
            "PRIVATE_VIDEO",
            "This video is private or restricted and cannot be ingested.",
            developer_message=message,
            stage=stage,
            suggestion="Use a public video or upload your own source file manually.",
        )
    if any(token in lowered for token in ("sign in", "login", "cookies", "age-restricted")):
        return LinkIngestionFailure(
            "LOGIN_REQUIRED",
            "This video requires login or age verification and cannot be ingested.",
            developer_message=message,
            stage=stage,
            suggestion="Use a public video or upload the file manually.",
        )
    if "drm" in lowered:
        return LinkIngestionFailure(
            "DOWNLOAD_FAILED",
            "This protected video cannot be ingested.",
            developer_message=message,
            stage=stage,
            suggestion="Use an unprotected source you are allowed to process.",
        )
    network_tokens = (
        "network",
        "connection",
        "temporary failure",
        "name resolution",
        "http error 5",
    )
    if any(token in lowered for token in network_tokens):
        return LinkIngestionFailure(
            "NETWORK_UNAVAILABLE",
            "Olympus could not access the video service.",
            developer_message=message,
            retryable=True,
            stage=stage,
            suggestion="Check the internet connection and try again.",
        )
    if "unavailable" in lowered or "not available" in lowered:
        return LinkIngestionFailure(
            "VIDEO_UNAVAILABLE",
            "This video is unavailable or cannot be accessed safely.",
            developer_message=message,
            stage=stage,
            suggestion="Check the URL or upload the source file manually.",
        )
    code = "PIPELINE_START_FAILED" if stage == "processing_started" else "DOWNLOAD_FAILED"
    user_message = (
        "The source was stored, but Olympus could not start processing it."
        if stage == "processing_started"
        else "Olympus could not ingest this video link."
    )
    return LinkIngestionFailure(
        code,
        user_message,
        developer_message=f"{type(exc).__name__}: {message}",
        retryable=stage != "processing_started",
        stage=stage,
        suggestion="Try again or upload the source file manually.",
    )


def _actual_selection(
    info: dict[str, Any],
    planned: dict[str, Any],
    upload: UploadRecord,
) -> dict[str, Any]:
    requested = [item for item in _list(info.get("requested_downloads")) if isinstance(item, dict)]
    if not requested:
        requested = [
            item for item in _list(info.get("requested_formats")) if isinstance(item, dict)
        ]
    format_ids = [str(item.get("format_id")) for item in requested if item.get("format_id")]
    video = next(
        (item for item in requested if str(item.get("vcodec") or "none") != "none"),
        {},
    )
    audio = next(
        (item for item in requested if str(item.get("acodec") or "none") != "none"),
        {},
    )
    resolution = planned.get("selected_resolution")
    if video.get("width") and video.get("height"):
        resolution = f"{video.get('width')}x{video.get('height')}"
    return {
        **planned,
        "selected_format_id": "+".join(format_ids) or planned.get("selected_format_id"),
        "selected_resolution": resolution,
        "selected_video_codec": video.get("vcodec") or planned.get("selected_video_codec"),
        "selected_audio_codec": audio.get("acodec") or planned.get("selected_audio_codec"),
        "selected_container": upload.video_format,
        "estimated_filesize": planned.get("estimated_filesize"),
        "actual_filesize": upload.size_bytes,
    }


def _format_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "format_id": _optional_text(item.get("format_id")),
        "ext": _optional_text(item.get("ext")),
        "width": _as_int(item.get("width")),
        "height": _as_int(item.get("height")),
        "fps": _as_float(item.get("fps")),
        "vcodec": _optional_text(item.get("vcodec")),
        "acodec": _optional_text(item.get("acodec")),
        "has_drm": bool(item.get("has_drm")),
        "filesize": _format_size(item),
    }


def _format_size(item: dict[str, Any]) -> int | None:
    return _as_int(item.get("filesize")) or _as_int(item.get("filesize_approx"))


def _preference_score(value: str, preferences: list[str]) -> int:
    for index, preference in enumerate(preferences):
        if preference and preference in value:
            return len(preferences) - index
    return 0


def _safe_filename(name: str) -> str:
    stem = PurePosixPath(name).stem.strip() or "linked-video"
    ext = PurePosixPath(name).suffix.lower()
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", " "} else "_" for ch in stem)
    safe = " ".join(safe.split())[:180].strip() or "linked-video"
    return f"{safe}{ext}"


def _content_type_for(ext: str) -> str:
    return {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".webm": "video/webm",
    }.get(ext, "application/octet-stream")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_text(value: Any) -> str | None:
    return str(value) if value is not None and str(value).strip() else None


def _bounded_text(value: Any, limit: int) -> str | None:
    text = _optional_text(value)
    return text[:limit] if text else None


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
