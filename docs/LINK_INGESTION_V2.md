# Link Ingestion V2

Olympus can ingest a supported public video link, store the resulting media as a normal project
source, and start the existing Analysis → Story → Virality → Planning → Editing → Rendering flow.
Manual file upload remains a separate intake option and uses the same downstream pipeline.

> Only use links to videos you own, have permission to use, or are allowed to process.

## Supported URLs

- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://youtube.com/shorts/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`

Olympus normalizes these to a canonical YouTube watch URL. Playlist-only URLs, arbitrary domains,
localhost, private/internal IP addresses, `file://` URLs, custom ports, embedded credentials, live
streams, private/login-only videos, and DRM-protected sources are rejected. Direct media URLs and
cookie-based authentication are disabled.

## Runtime Flow

1. `POST /api/v1/projects/from-link` validates rights confirmation and the URL.
2. The existing `VideoLinkIntakeService` extracts sanitized metadata with `yt-dlp`.
3. The API returns HTTP 202 with an ingestion id and starts the download in a background task.
4. The client polls `GET /api/v1/projects/link-ingestions/{ingestion_id}`.
5. `yt-dlp` downloads the best safe format at or below the configured height and reports progress.
6. FFprobe verifies that the result is a non-empty video with a valid duration.
7. Olympus stores it under `uploads/<upload_id>/source.<ext>`.
8. The existing `ProjectService` creates a normal project with `source_type=link`.
9. The existing Analysis service starts; downstream V2 completion hooks remain unchanged.

The background runner is process-local, matching the rest of the current Olympus local runtime. A
server restart interrupts an in-flight download, but the last persisted ingestion status remains
available. Run the backend without `--reload` for full processing validation.

## Configuration

Environment variables use the standard `OLYMPUS_` prefix and double-underscore nesting:

```env
OLYMPUS_LINK_INGESTION__ENABLED=true
OLYMPUS_LINK_INGESTION__ALLOWED_PLATFORMS=youtube
OLYMPUS_LINK_INGESTION__MAX_SOURCE_DURATION_MINUTES=120
OLYMPUS_LINK_INGESTION__MAX_SOURCE_FILE_SIZE_MB=4096
OLYMPUS_LINK_INGESTION__MAX_HEIGHT=1440
OLYMPUS_LINK_INGESTION__PREFERRED_CONTAINER=mp4
OLYMPUS_LINK_INGESTION__ALLOW_DIRECT_MEDIA_URLS=false
OLYMPUS_LINK_INGESTION__ALLOW_PLAYLISTS=false
OLYMPUS_LINK_INGESTION__ALLOW_LIVE_STREAMS=false
OLYMPUS_LINK_INGESTION__REQUIRE_USER_RIGHTS_CONFIRMATION=true
OLYMPUS_LINK_INGESTION__DOWNLOAD_TIMEOUT_SECONDS=7200
OLYMPUS_LINK_INGESTION__METADATA_TIMEOUT_SECONDS=60
OLYMPUS_LINK_INGESTION__CLEANUP_PARTIAL_DOWNLOADS=true
OLYMPUS_LINK_INGESTION__REPORT_PROGRESS_INTERVAL_SECONDS=1
```

Disable the feature with `OLYMPUS_LINK_INGESTION__ENABLED=false`.

## Dependencies

Install the repository's optional link extra in the project environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[video-links]"
```

FFmpeg and FFprobe must also be available through the configured binaries. Olympus never assumes a
globally installed `yt-dlp`; if the optional package is absent, the API reports
`DOWNLOADER_UNAVAILABLE` honestly.

## UI Validation

1. Start the backend without `--reload` and start the frontend.
2. Select **Paste Link**.
3. Paste a supported URL for a video you may process.
4. Confirm the rights notice and select **Create Shorts**.
5. Check metadata, download/merge/probe progress, then the normal project processing page.

The **Upload Video** tab remains available for manual sources.

## CLI Validation

Start with a dependency and backend diagnostic. Backend unavailability is a warning in
self-check because direct mode does not need the API:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py --self-check
```

Validate only URL syntax and the supported-source policy without contacting YouTube or
downloading:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "https://www.youtube.com/watch?v=VIDEO_ID" --diagnose
```

Direct mode isolates yt-dlp and local media tooling from the backend:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "https://www.youtube.com/watch?v=VIDEO_ID" --metadata-only --direct --confirm-rights

.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "https://www.youtube.com/watch?v=VIDEO_ID" --download-only --direct --confirm-rights
```

API mode checks TCP, liveness, OpenAPI, and both Link Ingestion routes before submitting
the URL:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "https://www.youtube.com/watch?v=VIDEO_ID" --metadata-only --api `
  --backend-url http://127.0.0.1:8000 --confirm-rights

.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "https://www.youtube.com/watch?v=VIDEO_ID" --download-only --api `
  --backend-url http://127.0.0.1:8000 --confirm-rights

.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "https://www.youtube.com/watch?v=VIDEO_ID" --full-pipeline `
  --backend-url http://127.0.0.1:8000 --confirm-rights --timeout-seconds 2400
```

Use a video you own, a video with explicit permission, or a suitable public-domain/Creative Commons
test source. Olympus does not ship a built-in test URL and never infers rights. Metadata-only does
not download media. Download-only stores and probes the source but does not create a project.
Full-pipeline requires the backend and waits for real rendered clips.

Every run writes:

- `work/validation_reports/link_ingestion/link_ingestion_validation_report.json`
- `work/validation_reports/link_ingestion/link_ingestion_validation_summary.md`

Use `--report-dir`, `--timeout-seconds`, and `--poll-interval-seconds` to override runtime
defaults. Direct downloads use isolated validator storage and are removed by default.
`--keep-download` copies only a completed, FFprobe-validated source into the report directory.
`--no-cleanup` preserves the isolated validator storage for debugging. API/project source files and
render outputs are never deleted by this validator.

## Structured Errors

Validator codes separate local backend failures from yt-dlp and media failures. Common codes include
`LOCAL_BACKEND_UNAVAILABLE`, `BACKEND_HEALTH_FAILED`, `API_ROUTE_UNAVAILABLE`,
`YTDLP_NOT_INSTALLED`, `YTDLP_METADATA_FAILED`, `URL_INVALID`, `UNSUPPORTED_SOURCE`,
`RIGHTS_CONFIRMATION_REQUIRED`, `VIDEO_UNAVAILABLE`, `LIVE_VIDEO_UNSUPPORTED`,
`AGE_RESTRICTED_UNSUPPORTED`, `DURATION_LIMIT_EXCEEDED`, `SIZE_LIMIT_EXCEEDED`,
`DOWNLOAD_FAILED`, `DOWNLOAD_INCOMPLETE`, `FFPROBE_FAILED`, `PROJECT_CREATION_FAILED`,
`PIPELINE_START_FAILED`, `PIPELINE_TIMEOUT`, `NO_CLIPS_RENDERED`,
`CLIP_VALIDATION_FAILED`, and `FRONTEND_PAYLOAD_FAILED`.

Each validator failure includes a code, message, likely cause, next action, exact command to try,
and bounded raw error. A Windows `WinError 10061` from the configured backend now means
`LOCAL_BACKEND_UNAVAILABLE`; it no longer appears as a generic YouTube/network failure. Persisted
backend ingestion errors retain their existing production contract.

## Limitations

- Initial support is YouTube-only; direct media links and playlists are disabled.
- No cookies, account sessions, private/member-only media, age-verification bypass, paywall bypass,
  or DRM bypass is supported.
- Download jobs are process-local rather than managed by a durable external queue.
- Format availability and public extraction behavior can change upstream; failures remain explicit.
- A real URL should be validated with a source the user is authorized to process before release.
- Direct mode validates yt-dlp and local binaries but cannot prove API or pipeline behavior.
- API metadata/download validation does not prove full rendering; only full-pipeline mode does.
- Self-check does not contact YouTube and therefore cannot prove external network access.
