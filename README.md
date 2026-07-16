# Project Olympus / ShortsCreator

Olympus turns uploaded or permitted linked videos into short-form editing plans,
vertical renders, and downloadable MP4 Shorts. The codebase keeps the original
Kiro architecture: FastAPI backend, Next frontend, storage-backed engine
artifacts, and separate Analysis, Story, Virality, Planning, Editing, Rendering,
Optimization, Workflow, Monitoring, and Library services.

## Local Windows Setup

Backend:

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe -m pip install -e ".[dev,transcription]"
copy .env.example .env
.\.venv\Scripts\python.exe -m uvicorn olympus.api.app:app --app-dir src
```

Use the no-reload command above for full upload/transcription/render validation.
`--reload` can watch generated media and build artifacts while Olympus writes to
`storage_data/`, `work/`, render folders, or `frontend/.next/`; that can restart
the dev server during heavy jobs. If you use reload while editing backend code,
exclude runtime paths such as `storage_data/*`, `work/*`, `.venv/*`,
`frontend/.next/*`, and `frontend/node_modules/*`.

Frontend:

```powershell
cd D:\Olympus\frontend
npm install
npm run dev
```

Open:

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- System info: http://localhost:8000/api/v1/system/info

## Required Local Tools

- Python 3.11+
- Node.js and npm
- FFmpeg and FFprobe on PATH
- faster-whisper for real transcription
- Optional: yt-dlp for video-link ingestion

Install optional link downloader support:

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe -m pip install -e ".[video-links]"
```

## Environment

For local end-to-end clip generation, `.env` should use:

```env
OLYMPUS_ENVIRONMENT=development
OLYMPUS_DEBUG=true
OLYMPUS_STORAGE__BACKEND=local
OLYMPUS_STORAGE__LOCAL_ROOT=./storage_data
OLYMPUS_RENDERING__BACKEND=ffmpeg
OLYMPUS_RENDERING__FFMPEG_BINARY=ffmpeg
OLYMPUS_AI__TRANSCRIPTION_PROVIDER=faster-whisper
OLYMPUS_AI__WHISPER_MODEL=tiny
OLYMPUS_AI__WHISPER_DEVICE=cpu
OLYMPUS_AI__WHISPER_COMPUTE_TYPE=int8
OLYMPUS_AI__WHISPER_BEAM_SIZE=1
OLYMPUS_AI__WHISPER_TIMEOUT_SECONDS=600
```

Use `tiny/cpu/int8` first. Larger Whisper models are optional after the full
workflow works.

## Olympus V2 Flow

1. Upload a local video, or paste a video link you own or have permission to edit.
2. Olympus stores the source media under local storage.
3. Project creation starts Analysis automatically.
4. Analysis extracts audio and transcribes speech.
5. Story and Virality produce evidence-backed narrative and retention signals.
6. Clip Planner V2 automatically selects all strong distinct clips the source
   deserves; the user does not choose a clip count.
7. Editing builds non-destructive timelines with hook, caption, motion, music,
   and SFX decisions.
8. Rendering starts after editing and produces vertical H.264/AAC MP4 files with
   burned captions when FFmpeg is available.
9. Rendered clips appear in the project overview gallery with preview and
   download buttons.

## V2 Behavior Added

- Uploads now carry content type, edit intensity, music, SFX, and caption intent
  into the project. Clip count is automatic.
- Video-link ingestion is available through `/api/v1/projects/from-link`.
- Link ingestion returns structured `validated`, `downloading`, `downloaded`,
  `failed`, or `unavailable` status. If yt-dlp is missing, Olympus explains the
  exact install command.
- Link downloads return an ingestion id and expose persisted progress through
  `/api/v1/projects/link-ingestions/{ingestion_id}`. See
  [`docs/LINK_INGESTION_V2.md`](docs/LINK_INGESTION_V2.md).
- Clip Planner V2 uses internal automatic clip-count bands:
  - 0-3 minutes: keep 1-3 strong clips
  - 3-10 minutes: keep 2-5 strong clips
  - 10-30 minutes: keep 4-10 strong clips
  - 30-60 minutes: keep 6-15 strong clips
  - 60-120 minutes: keep 10-30 strong clips
  - 120+ minutes: keep 15-40 strong clips, capped for local workload
- Planner candidates now include multi-pass transcript coverage across the full
  video: rolling windows, story/payoff moments, virality heat peaks, topic
  shifts, emotional/energy spikes, and fallback coverage windows.
- Ranking keeps all clips above the automatic quality floor, uses a lower
  secondary floor only when long-video coverage would otherwise be too sparse,
  deduplicates repeated/overlapping moments, and explains low output counts.
- Every plan includes V2 metadata: hook score/category, why selected, risk notes,
  source timestamps, music decision, SFX plan, and caption decision.
- Rendering does not claim music was included unless a real selected local asset
  exists.
- Captions V2 preserves real word timing when available, labels estimated timing,
  applies transcript-faithful emphasis, and publishes ASS/render proof. See
  [`docs/CAPTIONS_TYPOGRAPHY_V2.md`](docs/CAPTIONS_TYPOGRAPHY_V2.md).

## Rendered Clip Gallery

After rendering publishes a real manifest, the project overview replaces the
placeholder with clip cards. Each card uses the real rendered MP4 endpoint and
shows:

- browser preview player
- title, hook line, reason selected, source timestamps, and score
- MP4 download button
- copy title, description, and hashtag buttons
- platform-specific Upload Metadata V2 with bounded titles, captions, hashtags, and review warnings
- caption style, timing source, hook/emphasis, safe-zone, and validation truth

If rendering has not produced MP4s yet, the overview shows the current honest
state and points to the Rendering tab for exact logs.

## Music and SFX Assets

Olympus only uses royalty-free, user-provided, licensed, or locally available
music/SFX. Add assets under:

```text
assets/music/
assets/sfx/
```

Current V2 planning chooses the desired music mood and SFX category, but if no
local asset exists it marks the decision as `unavailable` with a reason. It does
not use copyrighted popular music automatically.

## Testing

Backend:

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy
```

Frontend:

```powershell
cd D:\Olympus\frontend
npm run typecheck
npm run lint
npm test
npm run build
```

Known mypy note: the configured package-level `mypy` run passes. The explicit
`mypy src tests` command can still fail before checking Olympus test code because
the installed NumPy stubs use Python 3.12 `type` syntax while the project mypy
target is Python 3.11. Pin compatible NumPy/stubs or run under a mypy setup that
accepts those stubs if you need that broader command.

## Testing With Videos

For a 3-minute video:

1. Use a speech-heavy video with several distinct points or payoffs.
2. Select `Auto` or `3` clips.
3. Wait for Analysis, Story, Virality, Planning, Editing, and Rendering.
4. Check Planning for multiple ranked plans and V2 reasoning metadata.
5. Download rendered MP4s from the Rendering tab.

For a 1-hour stream:

1. Use a video you own or have permission to edit.
2. Select `Auto` or 5-10 clips.
3. Expect transcription to take time on CPU.
4. Confirm candidates are distributed across the full source timestamps.
5. Render a subset first before rendering every selected clip.

## Current Limitations

- Advanced face tracking, CV scene analysis, beat detection, and true B-roll
  selection still report unavailable unless the required models/assets are
  added.
- Music and SFX are planned but not mixed unless local licensed assets are
  connected.
- FFmpeg rendering currently executes vertical crop, trim, captions, and a
  global punch-in when zoom events exist; not every timeline marker is rendered
  as a separate visual effect yet.
- Link ingestion depends on yt-dlp and on the linked site's availability and
  terms. Use it only for videos you own or have permission to edit.
