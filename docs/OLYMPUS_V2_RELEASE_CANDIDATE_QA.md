# Olympus V2 Release Candidate QA

Olympus V2 release-candidate QA is an evidence aggregator, not a release command. It does not
commit, tag, publish, upload to an external service, or convert a warning into a pass.

## Entry Point

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --fast
```

The canonical outputs are:

- `work/validation_reports/release_candidate/olympus_v2_release_candidate_report.json`
- `work/validation_reports/release_candidate/olympus_v2_release_candidate_summary.md`

## Modes

```powershell
# Full static, validator, backend, and runtime QA.
D:\Olympus\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --full --timeout-seconds 7200

# Full static suites and safe validators, but no slow real-media pipeline.
D:\Olympus\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --fast

# Backend/frontend static suites only.
D:\Olympus\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --static-only

# Runtime validators and media flow only.
D:\Olympus\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --runtime-only

# Reassess existing local artifacts without rerunning commands.
D:\Olympus\.venv\Scripts\python.exe tools\validate_olympus_v2_release_candidate.py --from-existing-reports
```

Useful options:

- `--sample FILE` selects an explicit local source.
- `--youtube-url URL --confirm-rights` permits a rights-confirmed public YouTube check.
- `--backend-url URL` changes the local API target.
- `--skip-frontend` records frontend checks as skipped; it cannot produce a ready decision.
- `--skip-slow` skips real-media work; it cannot satisfy the fresh-render gate.
- `--report-dir DIR` changes only QA report/runtime evidence storage.

## Safety

When full/runtime QA needs a backend and the configured loopback port is free, the validator starts
an isolated Uvicorn process without reload. It redirects storage, durable jobs, personalization, and
trend cache into the report directory. This prevents startup recovery from mutating the normal
`storage_data` or `work/jobs` baseline. The validator terminates only the process it created.

If a port is occupied but does not expose Olympus liveness, the validator reports the conflict and
does not kill the unknown process.

The URL workflow runs only when `--youtube-url` and `--confirm-rights` are both present. The tool
never supplies cookies, bypasses access controls, or selects private/login-only content.

## Evidence Contract

The top-level JSON key is `olympus_v2_release_candidate`. It records:

- repository identity and dirty-worktree counts;
- environment/tool versions and writable-location probes;
- exact static commands, exit codes, durations, and bounded output tails;
- normalized subsystem validator outcomes;
- local upload, link, long-video, durable, download, and final-MP4 evidence;
- rendered artifact and stale-report inventory;
- stable blockers and warnings with follow-up commands;
- completed features, limitations, non-claims, and recommended user tests.

Command execution always uses argument arrays with `shell=False`. A timeout, missing executable, or
non-zero exit is preserved in the report rather than converted into success.

## Release Decisions

- `PASS_RELEASE_CANDIDATE`: every blocker gate passes, a fresh local upload renders and validates,
  required tests pass, and no warnings remain.
- `PASS_WITH_WARNINGS`: every blocker gate passes and only documented non-critical warnings remain.
- `NOT_RELEASE_READY`: an important product or evidence gate is missing or failed.
- `BLOCKED`: the QA process itself cannot run because its Python validation environment is broken.

`release_candidate_ready` is true only for the two pass states. None of these states creates a
release or grants permission to publish.

## Blocker Gates

The validator blocks readiness when any of these are false or missing:

- backend import;
- local storage writability;
- FFmpeg/FFprobe and frontend tooling;
- `ruff`, `pytest`, `mypy`, frontend typecheck, lint, tests, and build;
- basic link, safety, upload-metadata, durable-job, API, and frontend checks;
- fresh local upload-to-render evidence;
- fresh downloaded MP4 validation;
- rendered safety and upload-metadata evidence;
- crash/resume/cancel/retry/duplicate durable simulations;
- required major-system documentation.

A prior MP4 or an old passing report does not satisfy the fresh-render gate.

## Warning Gates

Warnings remain explicit for unproven or non-critical evidence, including:

- no real 30+ minute full render;
- no rights-confirmed real YouTube full pipeline;
- no real backend kill/restart recovery;
- no manual playback/listening;
- no objective music audibility/speech-clarity analysis;
- no real face-tracked visual validation;
- no configured live search provider;
- no proven production curated music inventory;
- no clip-level partial-render resume;
- partial pre-project link-download durability;
- stale validator reports or bounded artifact inspection.

The canonical multi-speaker validator currently exposes `--simulate`, not the requested
`--synthetic` mode. QA runs `--simulate` and records `VALIDATOR_MODE_MISSING` until the command
contract is aligned.

## Real-Media Selection

Without `--sample`, QA probes local validation folders and normal uploaded source assets. It prefers
a valid real source between 3 and 20 minutes, then falls back to the shortest valid source. Rendered
outputs are excluded from source selection.

Thirty-minute validation requires direct duration evidence of at least 1800 seconds. A filename,
tier label, synthetic report, or stale project cannot satisfy that claim.

## Validation of the Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe -m pytest tests\unit\test_release_candidate_validation.py
D:\Olympus\.venv\Scripts\python.exe -m ruff check src tests tools
D:\Olympus\.venv\Scripts\python.exe -m mypy src
```

The tests cover every decision state, command failure capture, JSON/Markdown generation, stale
evidence, missing backend behavior, skipped real YouTube validation, and anti-overclaim gates for
fresh renders and 30+ minute sources.

## Interpretation

Automated passing evidence does not prove subjective editing quality. Music audibility, caption
comfort, face-tracking stability, and overall editorial quality still require playback on fresh
outputs. Copyright/safety results are conservative workflow metadata, not legal advice or a
copyright guarantee.
