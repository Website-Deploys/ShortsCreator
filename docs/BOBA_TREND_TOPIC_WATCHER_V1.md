# BOBA Trend / Topic Watcher V1

## Purpose

BOBA Trend / Topic Watcher V1 compares compact topic snapshots supplied by the
user or already saved by local BOBA modules. It identifies repeated, new,
rising, fading, stable, similar, and uncertain topics **within provided data**,
then creates an advisory topic watchlist.

V1 is deterministic and local. It does not establish external popularity or
predict audience performance.

## Boundaries

Trend / Topic Watcher V1:

- uses local or user-provided topic data only;
- does not scrape websites or platforms;
- does not fetch URLs;
- does not call external APIs;
- does not monitor YouTube, TikTok, Instagram, or any other platform;
- does not verify real-time trends;
- does not download, upload, or render media;
- does not store raw media, full transcripts, credentials, or auth tokens; and
- does not guarantee performance or replace human review.

Every movement claim means movement **within provided data**.

## Relationship To Other BOBA Modules

### Research Brain

Research Brain organizes local evidence, insights, claims to verify, and
research-supported topic ideas. Trend / Topic Watcher can read its saved topic
summary as one bounded local snapshot. It does not modify Research Brain.

### Content Scout

Content Scout reviews user-provided candidate metadata, tags, categories,
rights state, and possible content angles. Trend / Topic Watcher can read its
saved topic metadata as one bounded local snapshot. It does not ingest, score,
or mutate Scout candidates.

The watcher emits advisory handoffs for both modules with
`apply_automatically=false`.

## Inputs

Supported inputs are:

- local CSV files;
- local JSON files;
- manual snapshot objects;
- pasted compact topic lists;
- a saved Research Brain V1 artifact, when available;
- a saved Content Scout V2 artifact, when available;
- saved Creator Learning, Performance Feedback, and project memory signals,
  when available.

CSV and JSON files are limited to 2 MB. Import paths containing URL schemes are
rejected. Unsupported file types fail clearly. A malformed row is rejected
with a warning while other valid rows continue.

### Flexible Fields

Topic entries accept `topic`, `title`, or `keyword`, plus optional:

- description;
- tags and categories;
- user-provided rank;
- user-provided frequency;
- user-provided score;
- platform and source labels;
- capture date;
- evidence notes; and
- rights or safety notes.

Rank, frequency, and score remain absent when the user does not provide them.
V1 never fabricates numeric trend metrics.

JSON may be a list of objects or an object containing `topics`,
`topic_entries`, `items`, or `snapshots`.

## Topic Snapshots

Each snapshot preserves a source label, supplied capture time, optional
platform label, compact topic entries, warnings, and limitations. Snapshot
data is embedded in the single watcher artifact in V1; there is no separate
append log.

## Normalization

Topic labels are lowercased, stripped of punctuation, and whitespace-normalized.
Simple singular/plural variants are aligned. Near-duplicate matching uses a
conservative similarity threshold to avoid merging unrelated concepts.

## Movement Analysis

- **Repeated**: the normalized topic appears in multiple supplied snapshots.
- **New**: it appears only in the latest supplied snapshot set.
- **Rising within provided data**: comparable user-provided score, frequency,
  or rank improves.
- **Fading within provided data**: a comparable metric declines or the topic is
  absent from the latest supplied snapshot.
- **Stable**: the topic repeats with little comparable movement.
- **Duplicate or similar**: conservative normalization or similarity groups
  multiple labels.
- **Uncertain**: evidence is insufficient, vague, or lacks comparison data.

Saved Research Brain and Content Scout topic entries can support the analysis,
but they cannot override the latest comparable user-provided metric.

## Opportunity Scoring

Each topic receives bounded `0.0` to `1.0` advisory scores for:

- creator fit;
- Research Brain support;
- Content Scout support;
- shortability;
- hook potential;
- freshness within user data;
- risk; and
- overall topic priority.

Creator Learning, project memory, and manually entered Performance Feedback can
adjust fit conservatively. Performance Feedback contributes at most `0.08` in
either direction. Scores are explanations of local evidence, not forecasts.

## Watchlist And Confidence

The watchlist prioritizes strong opportunity scores, repeated or rising topics,
creator fit, and Research/Scout support. It includes reasons, suggested angles,
human-review notes, confidence, and warnings.

Confidence decreases when:

- only one snapshot exists;
- only one source label exists;
- no comparable user metric exists;
- labels are vague; or
- evidence is insufficient.

`not_real_time_verified` is always `true` in V1.

## Advisory Handoffs

The Content Scout handoff includes topics, keywords, categories, rights
reminders, and review questions. The Research Brain handoff includes topics,
claims and audience questions to verify, and source needs.

Candidate Video Scorer, Experimentation System, and Creator Learning integration
is reserved for future explicit work. V1 does not mutate any downstream module.

## Storage And Export

The canonical artifact path is:

```text
work/boba/projects/<project_id>/trend_topic_watcher/index.json
```

Storage uses the BOBA store's atomic JSON write path. Export removes local
source paths, source notes, evidence notes, and rights/safety notes, and marks
media, full transcripts, credentials, and raw source content as excluded.

Reset removes only the project's Trend / Topic Watcher artifact.

## API

```text
POST   /api/v1/boba/projects/{project_id}/trend-topic-watcher
GET    /api/v1/boba/projects/{project_id}/trend-topic-watcher
GET    /api/v1/boba/projects/{project_id}/trend-topic-watcher/export
DELETE /api/v1/boba/projects/{project_id}/trend-topic-watcher
```

POST accepts manual snapshots, pasted lists, local import paths, a source label,
and `dry_run`. A dry run returns analysis without persistence.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_trend_topic_watcher.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_trend_topic_watcher.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_trend_topic_watcher.py --project-id PROJECT_ID
```

Reports are written under:

```text
work/validation_reports/boba_trend_topic_watcher/
```

The synthetic validator uses compact local metadata only and proves movement,
bounded scores, advisory handoffs, persistence, safe export/reset, and all
no-network/no-media flags.

## Limitations

- Snapshot quality, dates, and source labels remain user responsibilities.
- Platform labels are descriptive and are not externally verified.
- Missing snapshots can make a topic appear new or fading.
- Similarity grouping can require human correction.
- Research and Scout support reflects saved metadata, not factual truth.
- No audience analytics, external popularity, or real-time monitoring exists.
- Human review remains required for claims, rights, strategy, and publication.
