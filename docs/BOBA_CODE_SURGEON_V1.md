# BOBA Code Surgeon V1

## 1. Purpose

BOBA Code Surgeon V1 is the bounded code-repair execution layer for Olympus.
It consumes persisted BOBA Repair Planner code-repair handoffs, verifies that
the handoff supports a code change, prepares a reviewable patch proposal, and
can apply an explicitly approved patch only inside a dedicated Git worktree
and repair branch.

The default mode is `proposal_only`. A passing patch still requires human
review and does not guarantee production correctness.

## 2. What Code Surgeon Does

Code Surgeon can:

- consume a saved Repair Planner handoff targeted to `code_surgeon`;
- accept one supported deterministic repair template or a reviewed unified
  diff;
- pin the proposal to an exact base commit SHA;
- constrain paths, scope, file types, file count, changed lines, and diff size;
- scan added patch content for likely credentials and private keys;
- verify that a patch applies cleanly without modifying the source worktree;
- bind execution approval to the exact base SHA, diff SHA, file scope, special
  paths, and validation commands;
- create a Windows-compatible isolated Git worktree and repair branch;
- run only registered validation commands with argument arrays and
  `shell=False`;
- roll back failed isolated attempts;
- prepare a local review commit after separate approval;
- generate bounded local PR title/body metadata;
- persist JSON-safe audit, validation, rollback, and review records.

## 3. What Code Surgeon Does Not Do

Code Surgeon does not:

- edit, commit to, reset, rebase, or otherwise modify `main` directly;
- push a branch, open a remote PR, merge, create a tag, deploy, or release;
- install or uninstall packages;
- restart services or control system processes;
- execute arbitrary shell text, pipes, redirects, chaining, or expansion;
- access the network, fetch URLs, call external APIs, or process media;
- modify credentials, secrets, `.env` files, generated state, or Git internals;
- bypass rights, safety, validation, or output-quality requirements;
- claim that every arbitrary defect can be repaired;
- claim that passing validation guarantees correctness or production readiness.

## 4. Relationship to Other BOBA Modules

### Repair Planner

Repair Planner is advisory. It identifies a supported repair strategy,
required scope, validation, rollback, approval, and stop conditions. It does
not create or apply code patches.

Code Surgeon consumes that persisted plan and refuses execution when the
handoff is missing, malformed, non-code, weakly supported, missing validation,
missing rollback, or otherwise ineligible.

### Tool Recovery Brain

A Tool Recovery Brain may eventually recover a missing or failing registered
tool. Code Surgeon only manages bounded source-code patches. It cannot install
tools, select unregistered executables, activate fallback tools, or restart
services.

### Safety Gate

Code Surgeon enforces its own branch, path, command, approval, and diff policy,
but does not replace Olympus safety or rights gates. A blocked upstream safety
or rights decision remains blocked.

## 5. Supported V1 Patch Sources

V1 accepts:

1. `deterministic_template` using
   `exact_text_replacement_v1`; or
2. a bounded reviewed diff identified as `user_provided_diff`,
   `codex_provided_diff`, or `imported_review_patch`.

V1 has no external coding-model provider and cannot invent a correct repair
for every failure.

## 6. Lifecycle and Modes

Supported modes are:

- `proposal_only`;
- `validate_provided_patch`;
- `approved_isolated_patch`;
- `prepare_local_review_commit`.

Diagnosis, explanation, planning, preview, and validation requests never imply
execution approval. Proposal and structural validation do not modify code.

## 7. Eligibility

Code changes normally require `strong` or `moderate` evidence from a saved
Repair Planner code handoff. Weak, conflicting, insufficient, unknown,
non-code, rights-blocked, or incomplete handoffs produce
`execution_eligible=false`.

The proposal records why a change is justified, behavior to preserve,
required validation, quality requirements, rollback requirements, confidence,
warnings, and limitations.

## 8. Approval Model

Isolated execution requires an explicit `isolated_patch_execution` approval.
The approval is valid only for the displayed:

- proposal and repair-case identifiers;
- base commit SHA;
- unified-diff SHA-256;
- exact changed-path scope;
- exact validation-command set;
- exact special-approval paths;
- approval expiry, when present.

A changed patch, base, scope, command set, approval type, or expired approval
blocks execution. A blocked proposal cannot execute even if an approval object
otherwise matches.

Creating a local review commit requires a second,
`local_commit_creation` approval. Execution approval never implies commit
approval.

## 9. Branch and Base Safety

Protected branches include `main`, `master`, `develop`, `release`, and
`release/*`.

Repair branches use a sanitized deterministic form:

`boba-repair/<project>/<case>-<short-slug>-<hash>`

The proposal stores the requested base branch and exact base commit SHA. The
SHA must still resolve before execution. Code Surgeon never silently advances
or substitutes the base.

## 10. Path and File Policy

Allowed text extensions include Python, TypeScript/JavaScript, JSON, TOML,
YAML, Markdown, CSS/SCSS, HTML, SQL, and text files.

Protected paths include:

- `.git/`, `.env`, secrets, credentials, and private keys;
- `work/`, `storage_data/`, media, uploads, and downloads;
- virtual environments, dependency trees, build output, and caches;
- validation reports and generated artifacts.

Binary, media, archive, executable, database, and compiled-file extensions are
blocked by default. Existing files are inspected for size and NUL bytes.
Absolute, UNC, drive-letter, traversal, control-character, repository-escape,
and symlink-escape paths are rejected.

Workflow files, dependency manifests and lockfiles, migrations, production
configuration, and infrastructure files require exact special-path approval.
File deletion, rename, and mode changes also require special review.
Submodules and Git LFS pointer changes are unsupported in V1.

## 11. Patch Limits

Default policy limits are:

- 12 changed files;
- 800 total added/deleted lines;
- 200,000 bytes per unified diff;
- 2 MiB per existing text file;
- 12 validation commands;
- 2 patch attempts;
- 300 seconds per command;
- bounded captured output.

Larger work requires an explicit bounded policy override and remains subject
to hard safety limits.

## 12. Secret and Quality Review

The proposed diff is scanned for likely tokens, passwords, credential URLs,
and private-key material. Findings are recorded as categories or redacted
fingerprints; secret values are not persisted or exported.

Patch-quality checks reject attempts to:

- delete or skip failing/regression tests;
- swallow broad exceptions;
- force always-success behavior;
- disable validation;
- weaken quality thresholds;
- bypass rights checks.

Permanent debug output is surfaced for review. A patch is not accepted merely
because it applies or because one test passes.

## 13. Isolated Worktrees and Patch Application

Approved execution creates:

`work/boba/code_surgeon/worktrees/<run_id>/`

The worktree is based on the approved SHA and uses the dedicated repair
branch. The patch is first checked with `git apply --check`, then applied only
inside that worktree. Code Surgeon verifies the exact changed-file set, runs
`git diff --check`, and rescans the diff before registered validation starts.

The original repository must be clean before execution and is compared again
during rollback. No command uses `shell=True`.

## 14. Trusted Validation Registry

V1's command registry contains:

- `git_diff_check`;
- `ruff`;
- `pytest` for bounded discovered test paths;
- `mypy`;
- `python_compile`;
- `frontend_typecheck`;
- `frontend_lint`;
- `frontend_test`;
- `frontend_build`.

Python validation is limited to approved `-m` modules. Direct scripts,
`python -c`, package installation, service control, network commands, unsafe
Git operations, shell metacharacters, pipes, redirects, and command chaining
are rejected.

Unknown, unavailable, skipped, timed-out, or failed required checks reject the
patch. Optional failures remain visible and are never mislabeled as passing.
Command output is streamed to temporary files, bounded, and redacted before
persistence.

## 15. Rollback

When patch application, changed-path verification, security review, or
required validation fails, Code Surgeon:

1. records the exact stop reason;
2. reverses the patch with a checked `git apply -R`;
3. verifies that the isolated worktree is clean;
4. removes the clean temporary worktree without force;
5. verifies that the original worktree remains unchanged;
6. persists an honest complete or partial rollback record.

An incomplete rollback remains visible and requires human review. The repair
branch is preserved for audit; Code Surgeon does not delete unrelated branches
or untracked user files.

## 16. Local Review Commit and Review Package

After required validation passes, separate approval may create one local
commit on the isolated repair branch. Only the exact approved files are
staged, the staged diff is checked, hooks and signing are disabled for the
bounded local operation, and amend is not used.

The review package includes a local commit SHA when created, bounded PR title
and body text, validation and rollback summaries, risks, changed files, and a
reviewer checklist. It always reports `ready_for_merge=false`; no remote PR,
push, or merge occurs.

## 17. API Routes

Project-scoped routes are:

- `POST /api/v1/boba/projects/{project_id}/code-surgeon/propose`;
- `POST /api/v1/boba/projects/{project_id}/code-surgeon/validate-patch`;
- `POST /api/v1/boba/projects/{project_id}/code-surgeon/execute-approved`;
- `POST /api/v1/boba/projects/{project_id}/code-surgeon/prepare-local-commit`;
- `GET /api/v1/boba/projects/{project_id}/code-surgeon`;
- `GET /api/v1/boba/projects/{project_id}/code-surgeon/export`;
- `DELETE /api/v1/boba/projects/{project_id}/code-surgeon`.

State-changing routes use the persisted Repair Planner and Code Surgeon
artifacts. The frontend displays proposal, evidence, file scope, risk,
validation, approval, execution, rollback, and human-review state without a
vague one-step repair action.

## 18. Artifact Paths

Local ignored artifacts are:

- `work/boba/projects/<project_id>/code_surgeon/index.json`;
- `work/boba/projects/<project_id>/code_surgeon/runs/<run_id>/index.json`;
- `work/boba/projects/<project_id>/code_surgeon/runs/<proposal_id>/patch.diff`;
- `work/boba/code_surgeon/worktrees/<run_id>/`.

The main JSON stores bounded summaries and references. The full reviewed diff
is stored separately under ignored work storage.

## 19. Export and Reset

Export returns a JSON-safe review package without full diffs, private
worktree paths, unbounded logs, or secret material.

Reset removes only Code Surgeon metadata. It does not delete source code,
Repair Planner or Root Cause Analyzer artifacts, branches, media, or unrelated
state. Reset refuses while an isolated worktree may still require review;
worktree cleanup is separate and explicit.

## 20. Validation

Run:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_code_surgeon.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_code_surgeon.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_code_surgeon.py --project-id PROJECT_ID
```

Synthetic validation uses a temporary Git repository and does not modify the
Olympus source worktree. Reports are written under ignored
`work/validation_reports/boba_code_surgeon/`.

## 21. Limitations

- Only `exact_text_replacement_v1` is supplied as a deterministic template.
- Reviewed diffs still depend on the reviewer or caller producing the intended
  implementation.
- Validation is scoped and cannot prove every runtime or production behavior.
- V1 does not install missing validators; an unavailable required validator
  rejects acceptance.
- V1 does not execute networked integration tests.
- V1 does not clean up a successful review worktree automatically because it
  may contain the local review state a human must inspect.
- Human review remains mandatory before any manual push, remote PR, merge,
  deployment, or release.
