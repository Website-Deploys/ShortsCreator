# BOBA Tool Recovery Brain V1

## 1. Purpose

Tool Recovery Brain V1 is the execution-capable, tightly bounded layer between an approved BOBA Repair Planner handoff and technical output validation. It recovers eligible local tool failures without granting authority over the wider Olympus workflow.

## 2. What It Does

It consumes a persisted Tool Recovery handoff, identifies the required capability, checks registered local providers, builds a failure-specific recovery ladder, verifies exact approval, executes an allowlisted local strategy, validates the generated artifact, rolls back failures, and prepares human-reviewed handoffs.

## 3. What It Does Not Do

V1 does not install or remove software, download tools or media, access the internet, call external APIs, use paid services, edit code, alter Git, restart services, kill unrelated processes, change source media, overwrite accepted outputs, bypass rights or safety gates, upload content, or resume Olympus automatically.

## 4. Repair Planner Boundary

Repair Planner remains advisory. It decides what class of recovery may be considered, supplies budgets and requirements, and creates the handoff. Tool Recovery accepts only a persisted `tool_recovery_brain` handoff and never mutates the Planner artifact.

## 5. Code Surgeon Boundary

Code defects remain Code Surgeon work. A Planner strategy requiring source changes makes Tool Recovery ineligible and creates a human-reviewed Code Surgeon handoff. Tool Recovery never edits repository files as a recovery action.

## 6. Checkpoint Recovery Boundary

Tool Recovery verifies that a required checkpoint is declared ready. Missing or invalid checkpoints block execution and route to Checkpoint Recovery Manager. V1 does not reconstruct or replace checkpoints.

## 7. Future Registry Boundary

The static V1 registry is not the future Tool Registry + Fallback Router. It contains only deterministic providers already supported by Olympus, performs local availability checks, and cannot discover, install, download, or mutate providers.

## 8. Capability-First Recovery

Recovery is selected by required capability rather than tool name alone. Initial capabilities are video/audio probe, video render, media decode/encode check, frame/audio extraction, local transcription, JSON artifact validation, and checksum validation.

## 9. Minimal V1 Capability Registry

The registry describes FFmpeg, FFprobe, optional PyAV/OpenCV/local Faster Whisper providers, internal JSON/checksum validators, and an explicitly blocked external transcription entry. Optional providers remain unavailable until a local health check proves otherwise.

## 10. Local Tool Health Checks

Health checks use structured argument arrays, `shell=False`, bounded time and output, a sanitized local environment, and no network. External-service health checks return `blocked`; missing executables and imports return `unavailable`; no installation is attempted.

## 11. Recovery Eligibility

Execution requires tool repair scope, a supported failure class, acceptable rights and safety state, a ready required checkpoint, usable rollback and validation plans, non-negotiable quality requirements, and a Planner strategy that needs no code change, package installation, service restart, external access, paid service, or destructive action.

## 12. Approval Binding

The approval must bind the exact recovery case, plan, one strategy, tool IDs, temporary settings, retry budget, total time budget, quality requirements, checkpoint reference, approver, timestamp, expiration, and confirmation:

> I approve this exact recovery strategy, registered tool, settings, retry budget, time budget, checkpoint reference, and quality requirements.

Any meaningful mismatch or expiration blocks execution before modification.

## 13. Retry Budgets

V1 permits at most two attempts per strategy, four attempts per plan, and 1,800 total seconds. A repeated failed strategy fingerprint is rejected. Each command also has a bounded timeout, so infinite or blind retry is impossible.

## 14. Recovery Workspace

Generated work is isolated under `work/boba/tool_recovery/workspaces/<attempt_id>/`. Inputs must be repository-relative and inside approved local roots. Outputs must be new files inside the attempt output directory. Traversal, absolute paths, UNC paths, symlink escapes, and existing-output replacement are rejected.

## 15. Trusted Command Registry

Only registered categories are accepted for each provider. Commands are arrays, never shell strings. Pipes, redirects, chaining, substitutions, URLs, unallowlisted options, package managers, network tools, Git, Python command execution, service control, process killing, and FFmpeg `-shortest` are rejected.

## 16. Failure-Specific Recovery Ladder

The ladder distinguishes unavailable executables, incompatibility, temporary or repeated crashes, timeouts, malformed output, unsupported input, resource exhaustion, configuration/environment/permission issues, generated-state issues, checkpoint problems, external services, and unknown failures. Unsafe cases stop or request evidence instead of retrying.

## 17. FFmpeg Recovery Profiles

Supported output-producing adapters include bounded retry, safe temporary settings, reduced thread/memory pressure, compatibility mode, registered local fallback, and segmented processing. Required duration, resolution, frame rate, audio, and A/V-sync properties remain unchanged.

Segmented processing supports FFmpeg `video_render` and `media_encode_check`, uses one parallel task, allows at most 16 bounded segments, validates every segment, concatenates compatible streams without `-shortest`, cleans segment files, and validates the final artifact again.

## 18. Registered Local Fallbacks

A fallback must already be registered, local, installed, capability-compatible, health-checked, quality-compatible, and explicitly approved. Unavailable, unregistered, external, paid, network-dependent, or install-dependent fallbacks are rejected.

## 19. Output Validation

Generated files must exist and be non-empty. Applicable checks include checksum, JSON schema, FFprobe readability, duration, source window, resolution/framing, frame rate, audio presence, A/V duration delta, and required caption timing. Missing required checks are failures, not passes.

## 20. Output-Quality Requirements

Tool Recovery never accepts an artifact merely because a process returns zero. A technical pass means `accepted_for_quality_review=true`; it is not final acceptance. Output Quality Reviewer remains mandatory and may still reject creative or perceptual quality.

## 21. Rollback

Command failure, timeout, or required validation failure rolls back recovery-owned generated state. Rollback removes only attempt outputs and temporary files, records partial cleanup honestly, preserves source media, accepted outputs, and checkpoints, and blocks further recovery when cleanup is incomplete.

## 22. Handoffs

Technical success creates Output Quality Reviewer, Safety Gate, and Workflow Controller handoffs. Blocked or failed work can route to Checkpoint Recovery Manager, Repair Planner, Root Cause Analyzer, Code Surgeon, Validator Runner, or a human operator. Every handoff defaults to `apply_automatically=false` and requires human approval.

## 23. API Routes

- `POST /api/v1/boba/projects/{project_id}/tool-recovery/plan`
- `POST /api/v1/boba/projects/{project_id}/tool-recovery/health-check`
- `POST /api/v1/boba/projects/{project_id}/tool-recovery/execute-approved`
- `POST /api/v1/boba/projects/{project_id}/tool-recovery/validate-output`
- `POST /api/v1/boba/projects/{project_id}/tool-recovery/rollback`
- `GET /api/v1/boba/projects/{project_id}/tool-recovery`
- `GET /api/v1/boba/projects/{project_id}/tool-recovery/export`
- `DELETE /api/v1/boba/projects/{project_id}/tool-recovery`

Planning and health routes do not grant execution approval. Validation does not grant final quality acceptance.

## 24. Artifact Paths

The current summary is persisted atomically at `work/boba/projects/<project_id>/tool_recovery/index.json`. Per-attempt snapshots are stored at `work/boba/projects/<project_id>/tool_recovery/runs/<attempt_id>/index.json`. Generated attempt artifacts stay under the separate recovery workspace and remain ignored.

## 25. Export and Reset

Export returns bounded, JSON-safe metadata with private absolute paths and unbounded command output excluded. Reset removes Tool Recovery metadata only. It does not delete Planner data, recovery workspaces, source media, checkpoints, or accepted outputs; an active attempt blocks reset.

## 26. Validator Commands

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_tool_recovery.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_tool_recovery.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_tool_recovery.py --project-id PROJECT_ID
```

Self-check validates imports, contracts, registries, workspace access, and shell/network/install boundaries. Synthetic mode runs 88 offline generated scenarios. Project mode is inspection-only. Reports are ignored under `work/validation_reports/boba_tool_recovery/`.

## 27. Limitations

V1 cannot solve every tool failure and does not claim production readiness. It supports output execution through registered FFmpeg adapters; optional providers remain unavailable when not installed. Segmented processing is limited to 16 segments. Synthetic proof does not establish quality for arbitrary real media. Technical success never equals final quality acceptance, and Olympus remains paused until separate human-reviewed control decisions complete.
