# Durable Job Queue / Resume V2

Olympus uses its existing Workflow Engine as the authoritative local job
scheduler. Durable Job Queue / Resume V2 extends that engine; it does not add a
parallel queue and does not require Redis, Celery, Docker, WSL, cloud services,
or paid APIs.

## Scope

Durable V2 provides:

- an additive `durable_job_v2` JSON contract for every project workflow;
- atomic local job mirrors and rebuildable indexes under `work/jobs`;
- stage leases, persisted heartbeats, stale-running recovery, retry, resume,
  cooperative cancellation, and duplicate project-job prevention;
- artifact-aware checkpoints for analysis, story, virality, planning, editing,
  rendering, optimization, and the source upload;
- global API, CLI, frontend, and validation surfaces.

It remains a single-machine system. It is not a distributed queue, and running
multiple API processes against the same local directory is not supported.

## Data Flow

The existing scheduler still owns execution:

1. A project gets one `project_pipeline` workflow and idempotency key.
2. The dependency scheduler claims one ready stage through a filesystem lease.
3. The in-process worker invokes the existing engine service.
4. Each engine persists its own versioned per-stage artifacts as before.
5. The worker inspects the engine artifact and records checkpoint truth.
6. Every workflow transition updates the canonical storage document and the
   local durable job mirror.
7. On startup, persisted running stages are marked stale, their orphan lease is
   removed, completed checkpoints are revalidated, and safe work is requeued.

No engine output is fabricated. A completed render checkpoint is valid only
when its manifest exists and every listed MP4 exists, matches measured
size/checksum metadata when present, and passes FFprobe. If FFprobe is
unavailable, the checkpoint stays invalid and the render stage is not skipped.

## Storage Layout

```text
work/jobs/
  jobs/
    job_<workflow-id>.json
  indexes/
    by_project.json
    idempotency.json
    queue.json
    running.json
  locks/
    <sha256>.lock/owner.json
  logs/
  reports/
```

The existing workflow document under the configured Olympus storage backend is
still canonical for backward compatibility. The `work/jobs` document is an
atomically updated durable projection used by indexes, diagnostics, and local
operations. Missing indexes are rebuilt from job documents.

Writes use a same-directory temporary file, flush, `fsync`, and `os.replace`.
This prevents readers from observing partial JSON, including on Windows. It
does not claim protection from every possible hardware/filesystem failure.

Potential secret-bearing keys such as tokens, passwords, cookies, and API keys
are removed from the local projection. Diagnostic log tails are bounded by
configuration.

## Job Contract

`durable_job_v2` includes identity, timing, status, priority, attempts,
idempotency, all stages, current progress, heartbeat/worker, resume state,
cancellation state, result truth, and bounded diagnostics.

Top-level statuses are:

- `queued`
- `running`
- `waiting`
- `completed`
- `failed`
- `canceled`
- `cancel_requested`
- `retrying`
- `stale`
- `blocked`

Stage statuses are `pending`, `running`, `completed`, `failed`, `skipped`,
`canceled`, and `stale`.

The original workflow API remains backward compatible (`cancelled` spelling and
the original internal scheduler states). The additive `durable_job_v2` view is
the stable V2 job contract.

## Checkpoint and Resume Rules

- Completed engine artifacts are skipped only while their persisted stage
  version remains current in the engine pipeline.
- Durable resume additionally verifies the checkpoint artifact exists and is
  readable.
- A missing/corrupt artifact or version mismatch invalidates that stage and all
  downstream stages.
- Source validation verifies the original stored source exists.
- Render validation never trusts a manifest whose MP4 is missing, empty, has a
  mismatched size/checksum, fails FFprobe validation, or cannot be probed.
- Partial clip rerender remains owned by the current Rendering Engine. Durable
  V2 does not claim clip-level partial rerender when the engine cannot do it
  safely; it resumes/reruns the render stage.
- Completed jobs do not resume by default.

## Retry and Cancellation

Automatic failures use the existing bounded exponential retry policy. Operator
retry resets failed/dead/blocked stages and unblocks downstream work while
preserving prior errors in the durable diagnostics.

Cancellation is cooperative:

1. the workflow persists the request;
2. queued stages are canceled immediately;
3. a running engine receives its existing cancellation signal;
4. the worker acknowledges cancellation after the stage reaches a safe point;
5. a finishing worker cannot resurrect a canceled stage.

Canceled jobs can be resumed; completed checkpoints are revalidated first.
Resume remains disabled while a running stage is still acknowledging a pending
cancellation request. If the backend restarts during that window, startup
recovery finalizes the orphaned cancellation before allowing resume.

## Duplicate Prevention

- One workflow document and idempotency key exist per project pipeline.
- Repeated start requests return the existing workflow.
- Atomic lock directories prevent two local workers from claiming the same
  stage.
- Heartbeats renew leases; startup removes leases belonging to orphaned
  persisted running stages.
- Existing artifacts are never deleted during stale recovery.

## Link Ingestion

Link metadata, rights confirmation, download progress, FFprobe result, source
asset, and project association continue to persist in the Link Ingestion V2
record. Once a link-created project starts processing, it is registered as the
same durable `project_pipeline` job and the link response exposes `job_id`,
`status_url`, and `resume_url`.

Current limitation: metadata extraction and the download/project-creation step
still use the existing FastAPI background task. A restart during that step can
leave the link record interrupted; this pass does not claim byte-range yt-dlp
download recovery. The created project's full analysis-to-optimization
pipeline is durable.

## API

- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/projects/{project_id}/jobs`
- `POST /api/v1/jobs/{job_id}/cancel`
- `POST /api/v1/jobs/{job_id}/retry`
- `POST /api/v1/jobs/{job_id}/resume`
- `GET /api/v1/jobs/{job_id}/events`
- `GET /api/v1/jobs/{job_id}/logs`

The original `/projects/{project_id}/workflow/...` endpoints remain available.

## Frontend

The existing project Workflow dashboard remains the single progress UI. It now
shows the durable job id, last heartbeat, checkpoint truth, stale/restart
warning, cancellation-pending warning, and resume controls. Projects whose old
API payload lacks `durable_job_v2` still render safely.

## Configuration

All options use the `OLYMPUS_DURABLE_JOBS__...` prefix. Important defaults:

- storage: `work/jobs`
- in-process runner: enabled
- heartbeat: 10 seconds
- stale threshold: 120 seconds
- attempts: 3
- completed retention: 14 days
- failed retention: 30 days
- diagnostic tail: 8000 characters

Set `OLYMPUS_DURABLE_JOBS__RUN_IN_PROCESS=false` to keep API-created jobs queued
for `tools/manage_jobs.py worker`. The CLI worker explicitly starts the pool in
that external-worker mode. `WORKER_POLL_INTERVAL_SECONDS` controls idle queue
polling.

## CLI

```powershell
.venv\Scripts\python.exe tools\manage_jobs.py list
.venv\Scripts\python.exe tools\manage_jobs.py show JOB_ID
.venv\Scripts\python.exe tools\manage_jobs.py project PROJECT_ID
.venv\Scripts\python.exe tools\manage_jobs.py resume JOB_ID
.venv\Scripts\python.exe tools\manage_jobs.py retry JOB_ID
.venv\Scripts\python.exe tools\manage_jobs.py cancel JOB_ID
.venv\Scripts\python.exe tools\manage_jobs.py recover-stale
.venv\Scripts\python.exe tools\manage_jobs.py worker
```

Use one API process or one CLI worker, not both concurrently. Do not use Uvicorn
`--reload` for long-running validation because reload intentionally kills the
worker process. One-shot CLI controls persist queue changes without launching a
short-lived worker; run the `worker` command (or enable the API in-process
runner) to execute them.

## Validation

```powershell
.venv\Scripts\python.exe tools\validate_durable_jobs.py --self-check
.venv\Scripts\python.exe tools\validate_durable_jobs.py --simulate-crash
.venv\Scripts\python.exe tools\validate_durable_jobs.py --simulate-resume
.venv\Scripts\python.exe tools\validate_durable_jobs.py --simulate-cancel
.venv\Scripts\python.exe tools\validate_durable_jobs.py --simulate-retry
.venv\Scripts\python.exe tools\validate_durable_jobs.py --simulate-duplicate
```

Reports are written to `work/validation_reports/durable_jobs` by default.
Self-check generates a tiny local MP4 with FFmpeg and validates its manifest,
size, prefixed SHA-256 checksum, and video stream with FFprobe.
Simulated crash/recovery proves persisted-state recovery logic; it is not a
claim that a real backend process was killed and restarted. Real restart testing
must be performed separately with a representative long video and without
`--reload`.
