# Final Release Validation V2

## Purpose

Final Release Validation V2 is the last local evidence gate for an Olympus V2 internal
release candidate. It aggregates existing validators; it does not replace their contracts,
change production engines, or turn synthetic evidence into a public-release claim.

The canonical result is `FinalReleaseValidationResultV1`. Every command is represented by a
`ValidatorResultV1`, including skipped and failed commands. The final verdict is exactly one of:

- `PASS_INTERNAL_RC`
- `BLOCKED`
- `INCOMPLETE`

`PASS_INTERNAL_RC` means the required deterministic local checks passed and no blocker was
found. It does **not** mean public production readiness, guaranteed quality, guaranteed
virality, or proof across arbitrary creator footage and devices.

## Commands

Run from the repository root:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_final_release.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_final_release.py --full
```

Optional modes:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_final_release.py --full --skip-slow
D:\Olympus\.venv\Scripts\python.exe tools\validate_final_release.py --inspect-reports
```

`--self-check` validates the environment but does not run rendering proofs, so a successful
self-check remains `INCOMPLETE`. `--skip-slow` explicitly skips real rendering, long-video, and
durable restart/resume proofs; because those checks are required, the verdict remains
`INCOMPLETE` unless another blocker makes it `BLOCKED`. `--inspect-reports` does not refresh
evidence.

No mode uses YouTube, downloads internet media, calls a cloud API, or uses private/user media.

## Validator Audit

| Validator | Self-check | FFmpeg | Optional dependencies | Main proof | Existing project inspection | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| `validate_test_assets_dependencies.py` | Yes | Tool discovery only | Reports all known optional packages | Clean-clone assets, imports, staged/generated-file safety | No | Required |
| `validate_analysis_signals.py` | Yes | Synthetic mode | CV/OCR/diarization providers are optional | Active core signals and honest optional fallbacks | Yes | Required |
| `validate_real_rendering_e2e.py` | No | Yes | No optional ML provider required | Synthetic upload through render, optimization, MP4, API, and frontend payload | Yes | Required |
| `validate_long_video_full_render.py` | Yes | Yes | No optional ML provider required | 30-minute synthetic source, multiple plans/renders, manifests, payload, and A/V proof | Yes | Required |
| `validate_durable_restart_resume.py` | Yes | Yes | No optional ML provider required | Resume after analysis/editing and during rendering | Yes | Required |
| `validate_face_tracking_motion.py` | Yes | Synthetic fallback uses FFmpeg | OpenCV optional | Fallback and motion rendering; real face proof only with rights-cleared input | Yes | Required synthetic proof; real proof limitation |
| `validate_multi_speaker_layout.py` | Yes | Synthetic mode uses FFmpeg | OpenCV optional | Two-speaker synthetic stack/layout render | Yes | Required synthetic proof; real proof limitation |
| `validate_av_sync_boundaries.py` | Yes | Simulation/stress modes | None | Timing contracts and synthetic A/V tolerance | Yes | Required |
| `validate_render_checkpoint_handoff.py` | Yes | Self-check uses simulated probe data | None | Canonical render checkpoint and optimization handoff | Yes | Required |
| `validate_boba_core.py` | Yes | No | None | BOBA Core contract/import health | Yes | Required contract check; advisory product behavior |
| `validate_boba_memory.py` | Yes | No | None | Local bounded memory contract health | Yes | Required contract check; advisory product behavior |
| `validate_rnd_boba_integrated.py` | `--all` only | No | None | Offline synthetic Core + Memory integration | No | Required contract check; advisory product behavior |

All listed tools write JSON evidence. Most accept a guarded report directory under
`work/validation_reports`; legacy BOBA tools write to their existing ignored directories and
the final validator copies their fresh JSON evidence into its guarded evidence tree. The final
report stores only compact facts and report references, not raw media paths or transcript/media
blobs.

## Required Checks

Backend gates:

- `ruff check src tests tools`
- `pytest tests/unit`
- `mypy src/olympus tools`

Frontend gates:

- `npm run typecheck`
- `npm run lint`
- `npm test`
- `npm run build`

Runtime/validator gates:

- Asset/dependency self-check and repository check
- Analysis-signal self-check and synthetic activation
- Real rendering E2E with a generated local source
- Thirty-minute synthetic long-video full render with at least three clips
- Durable resume after analysis, after editing, and during rendering
- Face/motion self-check and synthetic fallback render
- Multi-speaker self-check and synthetic two-speaker render
- A/V boundary self-check, simulation, and stress simulation
- Render checkpoint self-check and synthetic handoff simulation
- BOBA Core, Memory, and integrated offline checks

The render-heavy validators run sequentially with bounded FFmpeg thread settings. They must
produce fresh reports. An exit code of zero is insufficient when an expected report is missing,
invalid JSON, or lacks an explicit passing field.

## Blocker Rules

The gate returns `BLOCKED` when any blocker exists, including:

- Workspace Python/backend import, FFmpeg, FFprobe, npm, storage, or report access failure
- Missing required validator or frontend script
- Ruff, required unit tests, mypy, or frontend build failure
- Real rendering or 30-minute long-video proof failure
- Any required durable-resume mode failure
- Zero accepted MP4s
- Missing render or optimization manifest
- Invalid API/frontend payload
- A/V delta above `0.15` seconds
- Clean-clone asset/dependency failure
- Generated media, reports, caches, secrets, or environment files staged for commit
- A report that claims success while its manifests, payload, clip count, or A/V facts disagree

Required checks deliberately skipped or not run produce `INCOMPLETE`, not a pass. A blocker takes
precedence over incomplete evidence.

## Limitation Rules

The following are documented limitations rather than blockers for a synthetic internal RC:

- No real face-tracking proof without a rights-cleared face sample
- No real multi-speaker proof without a rights-cleared multi-speaker sample
- No real creator-footage proof when only generated sources were used
- No measured peak RAM value
- No operating-system process-kill proof when recovery used a new service instance in-process
- No manual music-quality or perceived voice/music-balance proof
- Missing optional transcription, CV, OCR, diarization, or object providers when absence is
  represented honestly and no required check depends on them

These limitations must remain visible even when the final verdict is `PASS_INTERNAL_RC`.

## Reports

Canonical reports are ignored generated files:

```text
work/validation_reports/final_release/final_release_report.json
work/validation_reports/final_release/final_release_summary.md
work/validation_reports/final_release/evidence/
```

The summary includes the Git revision, environment, backend/frontend status, validator table,
MP4 and manifest proof, long-video proof, durable-resume proof, analysis signals,
asset/dependency health, blockers, limitations, warnings, and final verdict.

Do not commit the report tree, generated sources, MP4s, `work/`, `storage_data/`, `media/`,
`.venv/`, `node_modules/`, `.next/`, `.env`, caches, or secrets.

## Remaining Proof Gaps

Even after `PASS_INTERNAL_RC`, public release evaluation still needs rights-cleared real creator
footage across representative codecs and durations, real face and multi-speaker samples, manual
visual/audio review, music-quality evaluation, peak-memory measurement, and a controlled real
process-kill/restart exercise. Those are separate proofs and are never inferred by this tool.
