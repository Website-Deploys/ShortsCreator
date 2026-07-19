# Durable Restart / Resume Proof V2

## Purpose

This validator proves that Olympus can persist a real durable workflow, stop its
in-process worker pool, construct a new `WorkflowService` instance over the same
storage, and continue from the persisted checkpoint graph. It uses only local,
generated media and the normal upload-through-optimization services.

It does not claim release readiness, real creator-footage coverage, distributed
worker recovery, or operating-system process-kill behavior.

## Durable State Audit

- Workflow state is stored at `workflow/<project_id>/workflow.json`.
- The complete workflow graph, job statuses, attempts, checkpoints, history, and
  recovery details are rewritten atomically through `StorageWorkflowRepository`.
- When enabled, `LocalDurableJobStore` mirrors the workflow as an atomic durable
  job document and rebuildable indexes.
- Each completed job stores an artifact-aware checkpoint in `Job.checkpoint`.
- Startup recovery reloads active workflows, validates completed checkpoints,
  leaves valid completed jobs untouched, and requeues orphaned `RUNNING` jobs as
  `STALE` then `READY`.
- A missing or invalid completed checkpoint resets that stage and all downstream
  stages instead of silently claiming reuse.
- Rendering and optimization pipelines independently skip completed,
  version-matched internal stages.
- The canonical rendering checkpoint is
  `render/<project_id>/run/index.json`; the legacy root index is fallback only.
- A render checkpoint is accepted only when its manifest is complete and every
  referenced MP4 exists, matches declared size/checksum, and passes FFprobe.
- Stage execution counts come from persisted durable `Job.attempts`; event
  history remains supporting evidence.

## What Is Proven

For each synthetic proof, the tool:

1. Generates or reuses an original 60-120 second local MP4.
2. Creates a unique storage namespace for the run so startup recovery cannot
   claim unrelated projects from shared `storage_data`.
3. Creates a normal Olympus project through intake/project services.
4. Starts the real durable workflow with one worker.
5. Interrupts at the selected deterministic point.
6. Stops the first worker pool and reads the persisted checkpoint.
7. Builds a second workflow-service/runtime instance over the same storage.
8. Calls startup recovery and explicit resume when required.
9. Waits for the real workflow to finish rendering and optimization.
10. Validates canonical manifests, real MP4s, API/frontend payload shape,
   duplicate outputs, partial outputs, and stage reuse/rerun accounting.

## Interruption Modes

### After Analysis

`--synthetic --interrupt-after analysis` pauses the workflow immediately after
the cognitive job is persisted as completed and before Story can be claimed.
The new service instance must reuse Upload and Cognitive Analysis.

### After Editing

`--synthetic --interrupt-after editing` pauses immediately after Editing's
completed checkpoint. The new service instance must reuse Upload through
Editing, then execute Rendering and Optimization.

### During Rendering

`--synthetic --interrupt-during rendering` waits until the durable Rendering job
has been claimed and persisted as `RUNNING`. A validator-only runner gate writes
a zero-byte `.part` marker and blocks before FFmpeg launch. Stopping the first
worker pool leaves the job honestly in-flight. The second service instance must
mark it stale, requeue it, increment its attempt count, run the real renderer,
and finish Optimization.

This is not a live FFmpeg or OS-process kill. Killing FFmpeg deterministically on
Windows risks leaving an uncontrolled subprocess. The report records the exact
method as
`validator_runner_gate_after_durable_claim_before_ffmpeg_then_new_service_instance`.

All hooks live in the validator and are disabled outside an explicit validation
run. Production workflow behavior is unchanged.

## Resume Pass Criteria

The proof passes only when:

- checkpoint JSON is readable before and after restart;
- no completed stage regresses or loses its checkpoint;
- completed stages retain their execution counts;
- an interrupted Rendering job is explicitly counted as rerun;
- at least one final MP4 exists and passes audio/video FFprobe validation;
- no partial output is referenced by the completed render manifest;
- no duplicate storage key or checksum is accepted;
- the canonical render manifest exists and is complete;
- the optimization manifest exists and is complete;
- the final API/frontend payload inspection passes;
- no validation errors remain.

## Checkpoint Integrity

The report records both checkpoint snapshots, every stage status, artifact path,
attempt count, reused/rerun classification, recovery reason, durable mirror
readability, and impossible-transition errors. Completed stages may be reused
only when their attempt count is unchanged and their checkpoint remains valid.

## Partial Output Checks

Rendered outputs fail validation when they are missing, zero bytes, use a
temporary `.part`/`.tmp` suffix, fail FFprobe, or lack either an audio or video
stream. The synthetic rendering interruption deliberately creates one unreferenced
partial marker so the validator can prove that it is detected and never accepted
as a manifest render.

## Duplicate Output Checks

The validator rejects repeated render storage keys and repeated SHA-256 content
checksums. The report identifies the original clip through `duplicate_of`.

## Commands

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_durable_restart_resume.py --self-check

D:\Olympus\.venv\Scripts\python.exe tools\validate_durable_restart_resume.py --synthetic --interrupt-after analysis

D:\Olympus\.venv\Scripts\python.exe tools\validate_durable_restart_resume.py --synthetic --interrupt-after editing

D:\Olympus\.venv\Scripts\python.exe tools\validate_durable_restart_resume.py --synthetic --interrupt-during rendering

D:\Olympus\.venv\Scripts\python.exe tools\validate_durable_restart_resume.py --project-id PROJECT_ID
```

`--project-id` is inspection-only. It compares the workflow checkpoint checksum
before and after inspection and does not resume, repair, rerender, or mutate it.

## Report Paths

Reports are restricted to:

```text
work/validation_reports/durable_restart_resume/
```

Each mode writes a JSON report and a compact Markdown summary. Synthetic media,
storage artifacts, reports, MP4s, caches, virtual environments, and secrets are
never publishable validator output.

## Validated Local Synthetic Runs

Validated on 2026-07-19 with FFmpeg and FFprobe available locally. An initial
development run revealed that using shared `storage_data` could recover unrelated
active validation projects. That run is not accepted as proof. Synthetic mode
now creates a unique physical storage namespace per invocation and fails if the
recovered-job count differs from the selected interruption mode.

| Mode | Project | Runtime | Reused | Rerun | Result |
| --- | --- | ---: | --- | --- | --- |
| After Analysis | `proj_80468624676b47c9a4e43787af659f5b` | 20.972s | Upload, Analysis | None | Passed |
| After Editing | `proj_eaa147f59a0a4340a12e8c66500be06b` | 21.516s | Upload through Editing | None | Passed |
| During Rendering | `proj_890ae174dfde447c854f241d04d4fcd7` | 20.419s | Upload through Editing | Rendering | Passed |

Each accepted run produced one real MP4, the canonical render manifest, a
completed optimization manifest, and a valid final API/frontend payload. No
duplicate accepted outputs or checkpoint corruption were detected.

The Rendering interruption persisted one `RUNNING` attempt, startup recovery
requeued exactly one job, and the final Rendering execution count was two. The
validator-created zero-byte `.part` output was detected before restart, was not
referenced by the manifest, and was cleaned before final validation.

Inspection-only mode was also run against the completed Rendering-interruption
project. The workflow checkpoint checksum was unchanged and no rerender or repair
was performed.

## Known Limitations

- Synthetic media and a deterministic transcript fixture are not real creator
  footage or transcription-accuracy proof.
- The validator creates a new service/runtime instance in the same Python
  process; it does not terminate and relaunch the Python interpreter.
- Rendering interruption happens after the durable job claim and before FFmpeg,
  not by killing a live FFmpeg subprocess.
- Local filesystem semantics do not prove distributed storage or multi-host
  locking behavior.
- Manual audiovisual playback is not performed.
- External APIs, YouTube, downloads, copyrighted media, and internet trend
  research are not used.
