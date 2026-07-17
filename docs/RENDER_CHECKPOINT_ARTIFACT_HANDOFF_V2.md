# Render Checkpoint Artifact Handoff V2

## Scope

This fix connects the completed Rendering Engine to the durable workflow checkpoint and
Optimization without changing rendering quality, clip timing, BOBA behavior, or frontend
features.

## Root Cause

The Rendering pipeline persisted its run index at:

`render/<project_id>/run/index.json`

Durable checkpoint validation and Optimization historically read the published manifest
from:

`render/<project_id>/index.json`

When only the run artifact remained, Rendering could produce real MP4s while the durable
job failed with a missing-checkpoint error. Optimization then stayed blocked even though
the render files were already present.

## Canonical Contract

The canonical durable Rendering checkpoint is now the storage-relative key:

`render/<project_id>/run/index.json`

New run indexes embed the published render manifest after the manifest stage completes.
The full stage artifact remains available at:

`render/<project_id>/run/stages/generate_render_manifest.json`

The physical local path is resolved through the configured storage root. With the default
local adapter, the canonical key maps to:

`storage_data/render/<project_id>/run/index.json`

The stored checkpoint remains storage-relative so it works consistently across local and
object-storage adapters.

## Resolution Order

The shared resolver supports:

1. A previously stored non-legacy checkpoint path, including an absolute path.
2. The canonical `run/index.json` artifact.
3. The legacy root `index.json` compatibility manifest.
4. The full `generate_render_manifest` stage artifact for older completed runs whose run
   index does not yet embed the manifest.

A stale stored legacy root path never outranks an available canonical run index. Legacy
lookup is fallback-only.

## Validation and Repair

Rendering is a valid durable checkpoint only when all of the following are true:

- The selected checkpoint JSON parses and reports `status=completed`.
- A completed render manifest is present and contains at least one output.
- Every referenced MP4 exists.
- Recorded sizes and checksums match when supplied.
- Every MP4 passes `ffprobe` video-stream validation.

Failures include the project ID, stage, stored path, canonical path, legacy path, storage
root, every searched path, resolved physical paths, manifest presence, MP4 presence, and
specific reasons.

Optimization is not started from the Rendering completion hook until this validation
passes. A persisted stale Rendering checkpoint can be repaired only after the same full
validation. Successful repair marks Rendering completed with the canonical artifact path
and re-arms blocked Optimization. Invalid artifacts do not change workflow status.

## Offline Validator

The validator uses local storage and no external APIs or downloads:

```powershell
.\.venv\Scripts\python.exe tools\validate_render_checkpoint_handoff.py --self-check
.\.venv\Scripts\python.exe tools\validate_render_checkpoint_handoff.py --simulate
.\.venv\Scripts\python.exe tools\validate_render_checkpoint_handoff.py --project-id <project_id>
.\.venv\Scripts\python.exe tools\validate_render_checkpoint_handoff.py --project-id <project_id> --repair
```

`--self-check` and `--simulate` use clearly labelled fake media bytes and a simulated
ffprobe result; they do not claim real-media validation. Project inspection and repair use
the configured real `ffprobe` binary.

Reports are written to:

- `work/validation_reports/render_checkpoint_handoff/render_checkpoint_handoff_report.json`
- `work/validation_reports/render_checkpoint_handoff/render_checkpoint_handoff_summary.md`

Synthetic artifacts stay under `work/rnd_validation/render_checkpoint/`. Both locations
are generated validation data and must remain untracked.

## Compatibility

- Existing legacy root manifests remain readable.
- Existing absolute checkpoint paths remain readable.
- Old canonical run indexes can recover their manifest from the persisted manifest-stage
  artifact.
- The legacy root manifest remains a compatibility publication for existing consumers.
- Existing rendered MP4s are neither moved nor deleted by validation or repair.

This pass does not address A/V sync, abrupt cuts, music audibility, face tracking,
multi-speaker layout, or any BOBA feature.
