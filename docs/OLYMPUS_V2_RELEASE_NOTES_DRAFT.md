# Olympus V2 Release Candidate Combined Systems — Draft

Status: **PASS_WITH_WARNINGS**

This pull request combines the completed Olympus V2 release-candidate work. It is not a final
release, production-readiness declaration, tag, or publish action. The unresolved warnings below
remain explicit blockers for any final-release claim.

## Included In This Candidate

- Real local-upload pipeline and guarded YouTube link ingestion.
- Story, Virality, Planning, Editing, Rendering, and Optimization V2 integration.
- Captions/Typography V2 with readability cleanup and render-truth validation.
- Music Intelligence, curated-library tooling, motion effects, and multi-speaker layout planning.
- Copyright/Safety metadata, upload metadata, and creator personalization.
- Durable jobs/checkpoints, long-video validation, and release-candidate QA tooling.

## What Olympus V2 Can Do

Olympus accepts a local video upload and can create a project, analyze and transcribe the source,
build story and virality intelligence, select clip plans, create editing timelines, render vertical
MP4 clips, run optimization/metadata stages, and expose results and downloads through the frontend.

The V2 worktree also contains guarded public YouTube-link ingestion, offline/cache-aware trend
research, music and SFX policy, captions/typography, motion effects, multi-speaker layout planning,
copyright/safety metadata, upload metadata, creator personalization, long-video validation, and a
local durable-job/checkpoint layer.

## Major Systems

- Story, virality, planning, editing, rendering, optimization, and `unified_clip_intelligence`.
- ASS captions with typography/readability metadata.
- Music intelligence, curated-library tooling, ducking/mix metadata, and safer SFX policy.
- Face/motion and multi-speaker layout plans with render-truth metadata.
- Internet trend research with evergreen/cache fallbacks and optional live providers.
- Safe link validation, rights confirmation, SSRF protections, metadata extraction, and download.
- Conservative copyright/safety and upload title/description/hashtag metadata.
- Creator profiles and feedback-driven personalization contracts.
- Local durable jobs with stage checkpoints, retry/cancel/resume controls, and diagnostics.
- Frontend result cards, downloads, warnings, personalization, and durable-job status surfaces.
- Subsystem validators plus the final release-candidate evidence orchestrator.

## Run Locally

Backend, without reload:

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe -m uvicorn olympus.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd D:\Olympus\frontend
npm run dev
```

## Test a Local Upload

Use the frontend upload flow, or run the release-candidate validator with an explicit source:

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --full --sample D:\path\to\source.mp4 --timeout-seconds 7200
```

The full validator uses an isolated local backend/storage area when port 8000 is free. It downloads
fresh results and checks them with FFprobe. A non-zero validator exit means the report contains a
blocker or the QA environment itself was blocked.

## Test a Video Link

Use only a public source that you own, have permission to process, or may lawfully process. Start
with metadata-only validation:

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe tools\validate_link_ingestion.py --metadata-only --direct --url "PUBLIC_URL" --confirm-rights
```

Then use full RC QA only after that succeeds:

```powershell
.\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --full --youtube-url "PUBLIC_URL" --confirm-rights --timeout-seconds 7200
```

Olympus does not use cookies or bypass private, login-only, member-only, live, or restricted media.

## Release-Candidate QA

Fast automated QA:

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --fast
```

Full QA:

```powershell
.\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --full --timeout-seconds 7200
```

Read the canonical decision and evidence in:

- `work/validation_reports/release_candidate/olympus_v2_release_candidate_report.json`
- `work/validation_reports/release_candidate/olympus_v2_release_candidate_summary.md`

## Known Limitations

- A/V sync or voice delay is still reported by the user and is not claimed fixed by this PR.
- Random clip cutting is still reported by the user and remains under investigation.
- No real 30+ minute full render has been completed.
- No controlled real backend kill/restart recovery validation has been completed.
- No end-to-end manual playback/listening QA has been completed.
- Face-tracked motion has not been proven on real face footage.
- The production curated music library remains starter-quality.
- Clip-level partial render resume is not claimed unless a current report proves it.
- Pre-project link-download durability is only partially proven.
- Music audibility and speech clarity require objective analysis and manual listening.
- Caption readability and safe-zone metadata do not replace viewing the actual MP4.
- Synthetic motion/layout validation does not replace real face/speaker footage playback.
- Local filesystem durability is not cloud-scale distributed job processing.
- Live trend coverage depends on configured providers; evergreen/cache fallback remains explicit.

## Not Claimed

- No guaranteed virality or guaranteed platform performance.
- No copyright guarantee, legal advice, fair-use determination, or Content ID prediction.
- No right to download or republish a third-party source.
- No bypass of YouTube restrictions, login gates, cookies, or private content.
- No Redis/Celery, multi-host, or cloud-scaling guarantee for the local durable-job layer.
- No manual visual or listening validation unless the report explicitly records it.
- No release-candidate or final-release status unless the canonical QA decision proves it and a human
  explicitly approves the release.

## Recommended Next Validation

1. Run a fresh full local upload pipeline and inspect every downloaded MP4.
2. Listen for speech clarity, music audibility, SFX cleanliness, and audio/video sync.
3. Watch caption-heavy and real face-tracked/multi-speaker samples.
4. Run a rights-confirmed real YouTube metadata check, download, and full pipeline.
5. Run planning and full rendering on a real 30+ minute source.
6. Perform a controlled backend kill/restart/resume test against isolated storage.
7. Open the frontend and verify old-project fallback, warning badges, copy controls, and downloads.
