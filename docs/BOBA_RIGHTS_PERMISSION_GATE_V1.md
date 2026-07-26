# BOBA Rights + Permission Gate V1

## Purpose

BOBA Rights + Permission Gate V1 is a conservative, metadata-only review layer
for candidate videos and other BOBA source items. It helps a human identify
declared rights status, missing permission evidence, review risks, and what must
happen before any future Olympus ingestion review.

V1 is not legal advice. It does not determine whether use is lawful or
copyright-safe.

## What It Does

- Combines local or user-provided rights metadata with saved BOBA Candidate
  Video Scorer, Content Scout, Research Brain, Trend Watcher, Clip Brief, Music
  Mood, and compact project-memory context.
- Normalizes declared rights statuses without treating declarations as proof.
- Produces one reviewed item, gate decision, permission checklist, risk review,
  and advisory future-ingestion handoff per accepted item.
- Preserves uncertainty and requires final human approval.
- Persists compact JSON that can be loaded, safely exported, or reset.

## What It Does Not Do

V1 does not:

- provide legal advice;
- verify copyright ownership;
- validate licenses, permissions, legal documents, fair use, or public-domain
  status;
- confirm copyright safety;
- fetch URLs or scrape platforms;
- call external APIs;
- download, upload, inspect, or ingest media;
- render clips or start Olympus processing;
- store raw media, full transcripts, full copyrighted source dumps, full legal
  documents, secrets, or authentication tokens.

## Difference From Candidate Video Scorer

Candidate Video Scorer ranks metadata-only candidates for editorial review and
includes a compact rights-readiness signal. Rights + Permission Gate does not
rank creative potential. It creates the dedicated evidence, checklist, risk,
decision, and future-ingestion precheck view. It reads Candidate Video Scorer
artifacts without mutating them.

## Inputs

The gate can use:

- manual rights-review entries;
- Candidate Video Scorer candidates and rights reviews;
- Content Scout items and declared rights statuses;
- Research Brain rights and source warnings;
- Trend Watcher rights notes;
- Clip Brief rights warnings;
- Music Mood audio-rights warnings;
- compact BOBA project memory.

All inputs remain local. A supplied source URL is retained only as a reference;
it is never fetched. Notes, tags, and categories are stored only as bounded
evidence snippets of at most 300 characters.

## Rights Status Handling

Supported declared statuses are:

- `owned`
- `licensed`
- `permission_granted`
- `permission_needed`
- `unknown`
- `blocked`
- `public_domain_claimed`
- `fair_use_claimed`

`owned`, `licensed`, and `permission_granted` can become
`ready_for_human_review` only when the matching compact note or reference is
present and no blocking conflict exists. This status permits human source
review only; it does not authorize ingestion.

`permission_needed` becomes `needs_permission`. `unknown`,
`public_domain_claimed`, and `fair_use_claimed` require rights review.
Unsupported statuses normalize to `unknown` with a warning. Claimed fair use or
public-domain status is never treated as proof. Explicit blocks, denied
permission, or do-not-process notes become `blocked`. Missing source identity
becomes `insufficient_information`.

Unknown rights are never treated as safe.

## Permission Checklist

Every reviewed item receives checks for:

1. ownership;
2. license;
3. permission;
4. platform/source terms;
5. third-party content;
6. music, audio, and SFX;
7. people, privacy, consent, and releases;
8. source identity and evidence quality;
9. final human approval.

Checklist passes describe only the presence of user-provided metadata. They are
not legal validation. Final human approval is always required.

## Risk Review

The risk review conservatively flags:

- unknown rights;
- third-party media;
- music/audio rights;
- platform terms;
- privacy or person-release needs;
- ambiguous source identity or conflicting notes;
- copyrighted-source cues;
- missing permission evidence.

Risk levels are metadata cues (`low`, `medium`, `high`, `blocked`, or
`unknown`), not legal conclusions.

## Gate Decisions

Gate statuses are:

- `ready_for_human_review`
- `needs_permission`
- `needs_rights_review`
- `blocked`
- `insufficient_information`

Only `ready_for_human_review` can be marked eligible for a future manual
ingestion precheck. Even then, the gate does not authorize or trigger ingestion.

## Future Ingestion Handoff

Every handoff is advisory and has `apply_automatically=false`. It records the
next human action and prerequisites. It never downloads, fetches, uploads,
ingests, or renders media.

Unknown, blocked, permission-needed, and insufficient-information items cannot
proceed to a future ingestion review. Ready items still require source review,
acceptable evidence, risk review, and explicit human approval.

Future ingestion requires human approval and acceptable rights status.

## Export And Reset

The export is a compact review artifact. It removes source URLs/references,
private ownership/license/permission/platform notes, and evidence snippets. It
also declares that paths, full transcripts, full legal documents, media,
credentials, and raw source content are excluded.

Reset deletes only the Rights + Permission Gate artifact. Candidate Scorer,
Scout, Research, Trend, Clip Brief, Music Mood, memory, and media artifacts are
not removed.

## Artifact Path

The persisted artifact is:

```text
work/boba/projects/<project_id>/rights_permission_gate/index.json
```

Writes use the existing BOBA atomic store pattern. The schema version is
`boba_rights_permission_gate_v1`.

## API

```text
POST   /api/v1/boba/projects/{project_id}/rights-permission-gate
GET    /api/v1/boba/projects/{project_id}/rights-permission-gate
GET    /api/v1/boba/projects/{project_id}/rights-permission-gate/export
DELETE /api/v1/boba/projects/{project_id}/rights-permission-gate
```

POST accepts optional manual metadata, a source label, and `dry_run`. It reads
saved local BOBA artifacts only. GET returns a clear missing-artifact response.
Export is compact and privacy-reduced. DELETE resets only this artifact.

## Validator

Run:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_rights_permission_gate.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_rights_permission_gate.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_rights_permission_gate.py --project-id PROJECT_ID
```

Reports are written under:

```text
work/validation_reports/boba_rights_permission_gate/
```

Reports are generated artifacts and must not be committed.

## Limitations

- Rights states and notes are supplied by users or existing local BOBA
  artifacts and may be incomplete or wrong.
- V1 does not inspect source media or legal documents.
- V1 does not know jurisdiction-specific law or validate platform permissions.
- V1 does not enforce ingestion; future ingestion and safety systems must
  consume the advisory handoff explicitly.
- Provider, legal-review, platform-policy, document-verification, and ingestion
  enforcement integrations remain future work.
- Human review is required before future processing.
