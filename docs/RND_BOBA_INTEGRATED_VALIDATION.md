# Integrated BOBA R&D Validation

`tools/validate_rnd_boba_integrated.py` provides one offline scenario that exercises BOBA Core
Brain V1 and BOBA Memory System V1 together. It is an R&D-only proof, not a production workflow
or media-quality test.

## Run

From `D:\Olympus`:

```powershell
.\.venv\Scripts\python.exe tools\validate_rnd_boba_integrated.py --all
```

`--all` is intentionally the primary mode. It creates one fake project, persists bounded
synthetic Olympus artifacts in a temporary directory, and runs the brain, observations,
decisions, ranking, editorial policy, project/creator/global memory, retrieval, explicit
learning, memory application, integration, API handlers, and frontend surface checks as one
connected scenario.

## Isolation

- Uses a project ID beginning with `rnd_boba_project_`.
- Writes only below `work/rnd_validation/boba_integrated/`.
- Deletes temporary scenario storage after the run.
- Does not read or modify production projects or `storage_data/`.
- Does not download videos, render media, publish content, or start the frontend server.
- Blocks socket connections while the scenario runs and fails if one is attempted.
- Stores only short synthetic text and rejects secret-like or large copied text.
- Uses deterministic trend fallback metadata instead of internet research.

## Reports

The command writes exactly these durable reports:

- `work/rnd_validation/boba_integrated/rnd_boba_integrated_report.json`
- `work/rnd_validation/boba_integrated/rnd_boba_integrated_summary.md`

The JSON report contains an explicit boolean for each integrated subsystem, plus warnings and
errors. `passed=true` means every checked BOBA contract and integration invariant passed inside
this isolated synthetic scenario, no socket call was attempted, and no media file was created.

## Limitations

A passing report does not prove production readiness, audience performance, copyright safety,
render correctness, face tracking, music audibility, A/V sync, clip-boundary quality, or durable
workflow recovery. Those require separate production-safe validation with authorized media. BOBA
directives remain advisory and are reported as unapplied in this R&D scenario.
