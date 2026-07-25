# BOBA Content Scout V2

## Purpose

BOBA Content Scout V2 is a project-scoped, metadata-only scouting brain. It helps a
creator decide which user-provided source ideas deserve human review, which need
permission, which should wait, and which must remain blocked.

Content Scout V2 is advisory. It does not guarantee performance or replace human
editorial and rights review.

## Scout V1 Compatibility

Scout V1 remains available for global candidate metadata, explicit approve/reject
actions, and Creative Director V1 handoff. Content Scout V2 does not replace or
delete those artifacts.

Content Scout V2 adds:

- project-scoped CSV, JSON, and manual metadata review;
- creator-fit and content-promise scoring;
- conservative rights and permission handling;
- separate top, backup, permission, blocked, and duplicate queues;
- possible short-angle suggestions;
- compact export and isolated reset.

Compatible local Scout V1 candidate metadata may be used as an advisory input. V2
stores its own artifact and never mutates Scout V1.

## Inputs

The engine can use:

- manually supplied metadata objects;
- a local CSV file;
- a local JSON file;
- BOBA Scout V1 candidate metadata, when available;
- Creator Learning preferences, when available;
- Approval/Rejection Learning patterns, when available;
- manual Performance Feedback patterns, when available;
- compact BOBA project memory, when available.

Missing optional BOBA artifacts trigger bounded fallback metadata. They do not stop
the scout review.

Content Scout V2 uses local/user-provided metadata only. It does not scrape
platforms, fetch URLs, download videos, call external APIs, store raw media, or
trigger ingestion or rendering.

## Metadata Import

### CSV

CSV headers are flexible. Supported names include:

`title`, `description`, `summary`, `url`, `source_url`, `source`,
`source_label`, `duration`, `duration_seconds`, `tags`, `categories`,
`category`, `creator`, `channel`, `creator_or_channel`, `published_at`,
`published_date`, `rights_status`, `permission_notes`, `notes`, and
`user_notes`.

Tags and categories may be comma-, semicolon-, or pipe-separated. Duration may be
numeric seconds or a colon-delimited value such as `01:30`.

### JSON

JSON may be:

- a top-level list of objects; or
- an object containing `items`, `source_items`, or `scout_items`.

### Manual

The API and Results panel accept a JSON array of metadata objects. A reference URL
may be retained as metadata, but BOBA does not open or fetch it.

Bad rows are rejected individually with a reason. Valid rows in the same import
continue through scoring.

## Scout Item

Each normalized item contains compact fields for title, description, source label
and reference, optional reference URL, duration, tags, categories, creator/channel,
published date, rights status, permission notes, user notes, and a small metadata
summary. It contains no media or transcript dump.

## Scoring

Every accepted item receives bounded `0.0`–`1.0` scores for:

- creator fit;
- topic fit;
- shortability;
- hook potential;
- emotional/story potential;
- supplied trend/context fit;
- novelty/diversity;
- rights readiness;
- overall review priority;
- confidence.

Scoring is deterministic and based only on supplied metadata and available local
BOBA advisory artifacts. Trend/context scoring uses supplied tags, categories,
published date, and user notes; it is not external trend verification. Duplicate
or substantially similar metadata receives reduced novelty.

## Rights And Permission Gate

Supported rights states are:

- `owned`
- `licensed`
- `permission_granted`
- `permission_needed`
- `unknown`
- `blocked`

`owned`, `licensed`, and `permission_granted` items may be eligible for
`review_now`. `permission_needed` and `unknown` remain in `seek_permission`.
`blocked` items remain in the blocked queue. Unsupported rights values normalize to
`unknown` with a warning.

These states are user-provided metadata. Content Scout V2 does not confirm
copyright safety.

## Recommendations And Review Queue

Recommendations are:

- `review_now`
- `save_for_later`
- `seek_permission`
- `reject`
- `blocked`

The review queue separates:

- top items;
- backup items;
- permission-needed or unknown-rights items;
- blocked items;
- duplicate or similar items.

Every recommendation remains human-review-required and includes reasons, risks,
questions, warnings, and limitations.

## Possible Short Angles

Promising metadata can receive one to three possible short angles. Angles are
phrased as review directions and are constrained to the supplied title,
description, and detected metadata terms. They do not invent source facts,
popularity, audience behavior, or rights clearance.

## Storage, Export, And Reset

The canonical project artifact is:

`work/boba/projects/<project_id>/content_scout_v2/index.json`

The BOBA store writes it atomically as JSON.

Export removes local import paths, reference URLs, permission notes, user notes,
raw metadata summaries, and review questions. It excludes media, full transcripts,
credentials, and secrets.

Reset deletes only the Content Scout V2 project artifact. Scout V1, Creator
Learning, Approval/Rejection Learning, Performance Feedback, and BOBA Memory remain.

## API

- `POST /api/v1/boba/projects/{project_id}/content-scout-v2`
- `GET /api/v1/boba/projects/{project_id}/content-scout-v2`
- `GET /api/v1/boba/projects/{project_id}/content-scout-v2/export`
- `DELETE /api/v1/boba/projects/{project_id}/content-scout-v2`

POST accepts `manual_items`, server-local `import_paths`, `source_label`, and
`dry_run`. A dry run returns the analysis without persistence. No route fetches a
URL, downloads a video, calls an external API, or starts Olympus processing.

## Validator

Run:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_content_scout_v2.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_content_scout_v2.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_content_scout_v2.py --project-id PROJECT_ID
```

Reports are written under:

`work/validation_reports/boba_content_scout_v2/`

They are generated artifacts and must not be committed.

## Future Handoffs

Content Scout V2 does not implement the future Candidate Video Scorer, Research
Brain, Trend Watcher, deeper Rights + Permission Gate, or approved Olympus
ingestion. Those modules may consume the compact scout artifact later, but no
handoff in V2 initiates an action.

## Limitations

- Metadata may be incomplete or inaccurate.
- Reference URLs are not inspected.
- No external trend or popularity information is verified.
- Scores do not predict an audience outcome.
- Suggested angles do not prove source content exists.
- Rights labels do not establish copyright safety.
- Human source, editorial, and permission review remains required.
- Content Scout V2 does not scrape, fetch, download, ingest, upload, render, or
  guarantee performance.
