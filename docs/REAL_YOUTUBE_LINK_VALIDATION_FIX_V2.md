# Real YouTube Link Validation Fix V2

`tools/validate_link_ingestion.py` is a local diagnostic and validation tool for the existing
Olympus Link Ingestion V2 implementation. It reuses `VideoLinkIntakeService`; it does not implement
a second downloader, API route, project flow, or frontend form.

## Safety Boundary

The validator:

- accepts individual YouTube watch, `youtu.be`, and Shorts URLs;
- requires explicit `--confirm-rights` before metadata extraction or download;
- uses the production no-cookie, no-playlist, no-login, no-DRM policy;
- rejects private, login-only, age-restricted, currently live, oversized, and over-duration inputs;
- stores only bounded report metadata;
- removes isolated direct-test files by default;
- never deletes API project sources or rendered outputs.

The validator does not bypass DRM, authentication, membership, age verification, regional
restrictions, or private-video controls. It does not include a copyrighted example URL and never
claims that the user has processing rights.

## Self-Check

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py --self-check
```

Self-check reports the Python executable and virtual environment, Olympus import, yt-dlp version,
FFmpeg and FFprobe versions, writable work/report directories, expected Windows workspace path,
backend TCP/liveness/OpenAPI state, and required API routes. A healthy local environment with no
running backend returns `WARNING`, because direct validation remains available.

Start the backend without reload for API or full-pipeline validation:

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe -m uvicorn olympus.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

## URL Diagnosis

This checks URL structure and source policy only. It does not contact YouTube and does not download:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "USER_PROVIDED_SAFE_URL" --diagnose
```

## Direct Mode

Direct mode isolates yt-dlp, FFmpeg, and FFprobe from backend/API availability.

Metadata only:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "USER_PROVIDED_SAFE_URL" --metadata-only --direct --confirm-rights
```

Download and probe:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "USER_PROVIDED_SAFE_URL" --download-only --direct --confirm-rights
```

Add `--keep-download` to copy the final validated source to the report directory. Without it, the
isolated source is removed. `--no-cleanup` preserves isolated validator storage; production
yt-dlp partial files are still removed by the canonical safety policy.

If direct metadata passes but API metadata fails, investigate backend health, URL/port, OpenAPI
routes, or backend environment rather than YouTube extraction.

## API Mode

API metadata:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "USER_PROVIDED_SAFE_URL" --metadata-only --api `
  --backend-url http://127.0.0.1:8000 --confirm-rights
```

API download:

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "USER_PROVIDED_SAFE_URL" --download-only --api `
  --backend-url http://127.0.0.1:8000 --confirm-rights
```

API mode stops before submitting the URL unless TCP, `/api/v1/health/live`, `/openapi.json`, and the
two Link Ingestion routes pass. It then reports metadata, selected quality, progress stage,
download/storage truth, and the backend FFprobe result.

## Full Pipeline

```powershell
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py `
  --url "USER_PROVIDED_SAFE_URL" --full-pipeline `
  --backend-url http://127.0.0.1:8000 --confirm-rights `
  --timeout-seconds 2400 --poll-interval-seconds 5
```

Full-pipeline mode verifies ingestion, normal project creation, processing start, project/workflow
and rendering status, a non-empty render manifest, real clip downloads, 1080x1920 dimensions,
video/audio codecs, audio/video duration delta within 0.15 seconds, manifest sync/duration truth,
and frontend-consumable clip IDs/metadata. Temporary validator copies of rendered clips are removed;
the backend's source and output files are untouched.

## Reports

Default files:

- `work/validation_reports/link_ingestion/link_ingestion_validation_report.json`
- `work/validation_reports/link_ingestion/link_ingestion_validation_summary.md`

The JSON contract is rooted at `link_ingestion_validation_v2` and includes environment, URL,
metadata, download, FFprobe, API, per-clip, stage, error, and final-result truth. The Markdown report
summarizes the same run and prints the exact next command on failure.

Use another directory when needed:

```powershell
--report-dir D:\Olympus\work\validation_reports\link_ingestion
```

## Error Guide

| Code | Meaning | First action |
| --- | --- | --- |
| `LOCAL_BACKEND_UNAVAILABLE` | Nothing accepts connections at the backend URL | Start the backend command shown in the report |
| `BACKEND_HEALTH_FAILED` | A process answered, but Olympus liveness failed | Verify the API app and URL |
| `API_ROUTE_UNAVAILABLE` | OpenAPI lacks required Link Ingestion routes | Start the current Olympus backend build |
| `YTDLP_NOT_INSTALLED` | Current Python cannot import yt-dlp | Install `.[video-links]` |
| `YTDLP_METADATA_FAILED` | Direct/public metadata extraction failed | Verify public availability and retry direct metadata |
| `RIGHTS_CONFIRMATION_REQUIRED` | Explicit confirmation was omitted | Rerun only if `--confirm-rights` is accurate |
| `VIDEO_UNAVAILABLE` | Private, deleted, login-only, or restricted | Use an authorized public source or manual upload |
| `DOWNLOAD_INCOMPLETE` | Stored file is absent or empty | Inspect isolated/API storage |
| `FFPROBE_FAILED` | Media or FFprobe is invalid/unavailable | Run self-check and repair FFmpeg |
| `PIPELINE_TIMEOUT` | Full pipeline exceeded its deadline | Inspect project status; increase timeout only if active |
| `NO_CLIPS_RENDERED` | Rendering produced no MP4s | Inspect planning/rendering manifests |
| `CLIP_VALIDATION_FAILED` | A rendered MP4 failed real media checks | Inspect per-clip report details |

`WinError 10061` specifically means the configured local host/port refused the backend connection.
It maps to `LOCAL_BACKEND_UNAVAILABLE`; it does not prove that YouTube or internet access failed.

## Honest Validation Levels

- Self-check proves local dependencies and optionally backend routes, not YouTube access.
- Diagnose proves URL policy only.
- Direct metadata proves yt-dlp metadata extraction only.
- Direct download proves download and local FFprobe only.
- API metadata/download proves backend integration only through the requested stage.
- Full-pipeline proves rendered clips only when it actually completes and validates those MP4 files.
- Real validation requires a safe URL supplied by a user who accurately confirms processing rights.
