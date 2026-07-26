# BOBA Candidate Video Scorer V1

## Purpose

BOBA Candidate Video Scorer V1 evaluates candidate source-video metadata and
builds an advisory human review queue. It helps a creator decide which
candidate records may deserve source review, which require permission, and
which should be blocked or rejected.

V1 is deterministic and local. It uses local or user-provided metadata and
saved BOBA artifacts only.

## Safety Boundary

Candidate Video Scorer V1 does not:

- fetch URLs;
- scrape websites or platforms;
- call external APIs;
- download or upload videos;
- inspect or ingest media;
- render clips or start Olympus processing;
- verify popularity or real-time trends;
- confirm ownership, license scope, permission, or copyright safety;
- guarantee audience performance.

A stored URL is metadata text only. Human approval and rights review are
required before any future ingestion.

## Relationship To Existing BOBA Modules

### Content Scout V2

Content Scout imports and prioritizes broad local source-item metadata.
Candidate Video Scorer performs a deeper source-video-oriented evaluation:
Shorts potential, story and format fit, explicit rights readiness,
recommendations, review queues, and future handoffs. It reads Content Scout
artifacts without mutating them.

### Research Brain V1

Research Brain organizes local evidence, insights, hook directions, and Shorts
ideas. Candidate Video Scorer uses matching research topics and ideas as
bounded support. It does not treat research ideas as rights-cleared videos.

### Trend / Topic Watcher V1

Trend Watcher compares topics only within supplied snapshots. Candidate Video
Scorer may raise trend support when candidate metadata matches watched topics.
This is not real-time trend verification.

### Learning And Memory

Creator Learning, Approval/Rejection Learning, Performance Feedback, and
project memory may adjust creator fit conservatively. Approval and performance
adjustments are individually bounded to `+/-0.08`. The scorer does not mutate
these artifacts.

## Inputs

The engine accepts:

- manual candidate objects;
- local CSV files;
- local JSON files;
- saved Content Scout V2 items;
- saved Research Brain Shorts ideas;
- saved Trend Watcher watched topics;
- optional saved creator, approval/rejection, performance, and memory signals.

Bad rows are rejected independently and recorded as warnings. They do not
abort the entire import.

## CSV Import

Common flexible headers include:

- `title`
- `description`
- `url` or `source_url`
- `source` or `source_label`
- `creator` or `channel`
- `duration`
- `published_at`
- `tags`
- `categories`
- `rights_status`
- `permission_notes`
- `notes`

Only local `.csv` paths are accepted. Import files are limited to 2 MB.

## JSON Import

JSON may be:

- a list of candidate objects; or
- an object containing `candidates`, `candidate_videos`, `items`, or
  `source_items`.

Only local `.json` paths are accepted. Import files are limited to 2 MB.

## Candidate Record

Each `BobaCandidateVideoV1` stores compact metadata:

- stable candidate ID;
- title and description;
- source label and reference;
- optional source URL retained as un-fetched text;
- optional duration, creator/channel, and published date;
- topic tags and categories;
- user-provided rights status and permission notes;
- user notes and source-artifact references;
- compact metadata summary, warnings, and limitations.

Raw media, full transcripts, full source dumps, secrets, and auth tokens are
not stored.

## Scoring

`BobaCandidateVideoScoreV1` contains clamped `0.0` to `1.0` scores for:

- creator fit;
- topic opportunity;
- research support;
- trend support within provided data;
- shortability;
- hook potential;
- story potential;
- format fit;
- rights readiness;
- risk;
- review priority;
- overall candidate quality;
- confidence.

Scoring uses supplied words, categories, durations, rights states, and bounded
saved BOBA signals. It does not fabricate views, engagement, rankings,
popularity, or audience predictions.

## Shorts Potential Review

The scorer generates possible:

- clip types;
- hook directions;
- story angles;
- format styles;
- emotional or story promise;
- likely weaknesses;
- human review questions.

These fields use conditional language such as "possible" and "may." They do
not assert that unseen source media contains a specific moment.

## Rights And Permission Review

Supported user-provided rights states are:

- `owned`
- `licensed`
- `permission_granted`
- `permission_needed`
- `unknown`
- `blocked`

The derived readiness values are:

- `ready_for_review`
- `needs_permission`
- `unknown_needs_review`
- `blocked`

Owned, licensed, or permission-granted metadata may allow human source review.
`permission_needed` recommends seeking permission. `unknown` always requires
rights review and is never treated as safe. `blocked` prevents any future
ingestion. None of these states confirm copyright safety.

## Recommendations And Review Queue

Advisory recommendations are:

- `review_now`
- `save_for_later`
- `seek_permission`
- `reject`
- `blocked`

The review queue separates:

- top candidates;
- backup candidates;
- permission-needed candidates;
- blocked candidates;
- duplicate or similar candidates;
- rejected candidates.

Duplicate detection is intentionally conservative and uses exact references,
normalized titles, or very high title similarity. Recommendations always
include a next human action.

## Source Handoffs

The artifact includes advisory handoffs for:

- Content Scout;
- Research Brain;
- Trend Watcher;
- a future Rights + Permission Gate;
- future video ingestion after human approval and rights readiness.

Every handoff has `apply_automatically=false`. V1 does not change another BOBA
artifact or start ingestion.

## Artifact Storage

The atomic artifact path is:

```text
work/boba/projects/<project_id>/candidate_video_scorer/index.json
```

The schema version is `boba_candidate_video_scorer_v1`. Old projects without
this artifact continue to load and receive a clear unavailable response.

## API

```text
POST   /api/v1/boba/projects/{project_id}/candidate-video-scorer
GET    /api/v1/boba/projects/{project_id}/candidate-video-scorer
GET    /api/v1/boba/projects/{project_id}/candidate-video-scorer/export
DELETE /api/v1/boba/projects/{project_id}/candidate-video-scorer
```

POST accepts manual candidate objects, local CSV/JSON paths, a source label,
and `dry_run`. Dry runs are not persisted.

DELETE removes only the Candidate Video Scorer artifact.

## Export

The compact export excludes:

- local import paths;
- source URLs;
- permission and user notes;
- raw metadata summaries;
- full transcripts and raw source content;
- media files;
- credentials.

Export privacy metadata explicitly records that external APIs, URL fetching,
scraping, downloading, media ingestion, and copyright-safety confirmation did
not occur.

## Frontend

The Results view shows:

- import summaries;
- scored candidate cards and score breakdowns;
- Shorts potential and rights reviews;
- recommendations and next human actions;
- every review queue;
- advisory source handoffs;
- warnings;
- safe export and scorer-only reset controls.

The panel does not provide URL fetching, downloading, ingestion, or
copyright-safety controls.

## Validator

Run:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_candidate_video_scorer.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_candidate_video_scorer.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_candidate_video_scorer.py --project-id PROJECT_ID
```

Reports are written under:

```text
work/validation_reports/boba_candidate_video_scorer/
```

Reports are generated artifacts and must not be committed.

## Tests

Run the focused 56-test suite:

```powershell
D:\Olympus\.venv\Scripts\python.exe -m pytest tests/unit/test_boba_candidate_video_scorer.py
```

The suite covers contracts, imports, rights behavior, scoring signals,
duplicates, queues, storage, API routes, export/reset, validator behavior, and
proof that no rendering, download, URL fetch, external call, or media ingestion
is triggered.

## Limitations

- Metadata may be incomplete, inaccurate, or misleading.
- The scorer does not inspect source video or audio.
- Rights states and permission notes are not independently verified.
- Research and trend support is limited to saved user-provided data.
- Duplicate detection is metadata-based.
- Shorts directions remain hypotheses until a human reviews the source.
- Scores do not guarantee performance or production readiness.
- A future Rights + Permission Gate and future ingestion flow remain separate.
