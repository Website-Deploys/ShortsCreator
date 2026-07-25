# BOBA Performance Feedback Brain V1

## Purpose

BOBA Performance Feedback Brain V1 turns explicit creator-entered results into
bounded, advisory evidence about clips and experiments. It helps identify
repeated winners, repeated weak patterns, contradictions, and evidence that is
too limited to support learning.

V1 does not predict performance or guarantee virality.

## Relationship To Other BOBA Systems

The Experimentation System proposes controlled advisory comparisons and stores
manual experiment results. Performance Feedback reviews those results together
with other creator-entered clip outcomes.

Creator Learning records explicit preferences and corrections. Approval /
Rejection Learning reviews explicit decisions. Performance Feedback does not
replace either system; it creates a separate advisory handoff that a creator can
review before any future learning action.

## Manual Performance Events

Supported explicit event types are:

- manual clip result
- manual experiment result
- manual rating
- manual note
- creator interpretation
- reset/export audit event shapes

Every accepted event is marked `user_entered=true`. V1 has no platform
connection, scraper, analytics API, hidden behavior collector, or background
metric ingestion path.

## Optional Metric Snapshots

Creators may enter views, likes, comments, shares, saves, watch-time values,
retention, click-through rate, completion rate, follower gain, manual rank, and
bounded custom metrics. Every metric is optional and has no fabricated default.

Negative counts and impossible percentage ranges are rejected. Missing metrics
lower confidence. More entered metrics, a manual rating, and explanatory notes
can increase confidence, but values remain unverified creator input.

## Experiment Outcome Review

Saved Experimentation plans can be linked to a manual baseline or variant
result. Reviews preserve:

- the chosen baseline or variant
- what likely worked or failed
- cautious success and failure factors
- confidence and limitations
- proposed learning targets

Inconclusive results do not produce strong learning. No winner is applied
automatically.

## Pattern Summary

The brain groups compatible factors across clips and experiments. Repeated
consistent results increase factor confidence. A single result remains weak
evidence. Positive and negative results for the same pattern are retained as a
contradiction and reduce summary confidence.

Pattern output includes hook, retention, payoff, caption, motion, music mood,
SFX, speech clarity, clip type, platform fit, and general factors when the
corresponding local BOBA evidence exists.

## Learning Handoff

The output can propose advisory updates for:

- Creator Learning
- Approval / Rejection Learning
- Experimentation
- Ranking and Editorial systems
- Hook + Retention
- Caption + Motion
- Music Mood

`apply_automatically` is always `false` in V1. Generating feedback does not
mutate prior BOBA decisions or memory records.

## Confidence And Weak Data

Confidence reflects only the amount and consistency of entered evidence. It is
not an audience-performance probability. Missing metrics, absent artifacts,
single observations, inconclusive experiments, and contradictions produce
warnings or limitations.

Cross-platform values are not treated as directly comparable without creator
context.

## Storage

Project-scoped artifacts are stored atomically under:

```text
work/boba/projects/<project_id>/performance_feedback/index.json
work/boba/projects/<project_id>/performance_feedback/events.jsonl
```

The summary has schema version `boba_performance_feedback_v1`. Event writes are
deduplicated by event ID and preserve prior valid events.

## Export And Reset

Export returns compact JSON and excludes creator notes, retention notes, factor
evidence, media, source text, credentials, and platform connections.

Reset removes only the project’s Performance Feedback summary and event log. It
does not remove Experimentation, Creator Learning, Approval / Rejection
Learning, or BOBA Memory artifacts.

## API

```text
POST   /api/v1/boba/projects/{project_id}/performance-feedback/events
POST   /api/v1/boba/projects/{project_id}/performance-feedback
GET    /api/v1/boba/projects/{project_id}/performance-feedback
GET    /api/v1/boba/projects/{project_id}/performance-feedback/export
DELETE /api/v1/boba/projects/{project_id}/performance-feedback
```

The summary POST accepts `{"dry_run": true}`. A dry run returns advisory output
without saving the summary.

## Frontend

The project Results view provides a manual-entry panel with optional metrics,
ratings, creator notes, retention notes, experiment outcomes, summaries,
warnings, export, and project-scoped reset controls. It explicitly states that
V1 does not connect to platforms or collect analytics.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_performance_feedback.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_performance_feedback.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_performance_feedback.py --project-id PROJECT_ID
```

Reports are written under
`work/validation_reports/boba_performance_feedback/` and remain ignored.
Synthetic validation uses local metadata only; it does not require media,
secrets, rendering, uploads, downloads, analytics, or network access.

## Limitations

- V1 accepts manual input only and cannot verify platform metrics.
- It does not scrape YouTube, Instagram, TikTok, or any other platform.
- It does not call analytics or other external APIs.
- It does not collect hidden behavior.
- It does not render, upload, or download media.
- It does not establish causality or guarantee future performance.
- It does not automatically apply experiment winners.
- It does not replace human editorial review.
