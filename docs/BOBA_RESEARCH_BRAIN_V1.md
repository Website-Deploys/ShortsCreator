# BOBA Research Brain V1

## Purpose

BOBA Research Brain V1 converts local or explicitly user-provided text material
into bounded, traceable editorial research. It is an advisory module: it suggests
possible topics, hooks, formats, and Content Scout search guidance without
automatically changing any downstream BOBA decision.

## What It Does

Research Brain V1:

- imports local TXT, Markdown, CSV, and JSON files;
- accepts manual records and pasted text;
- retains compact source summaries and bounded evidence snippets;
- extracts deterministic topic, audience, hook, format, tension, caution, and
  verification insights;
- proposes source-linked Shorts ideas;
- reports evidence, rights, copyright, sensitivity, and verification risks;
- creates an advisory handoff for Content Scout V2; and
- supports project-scoped persistence, safe export, and reset.

The engine uses deterministic local heuristics. It does not claim that an idea is
popular, trending, accurate, copyright-safe, or likely to perform.

## Research Brain vs. Content Scout

Research Brain analyzes the contents of user-provided text material. Content
Scout V2 scores user-provided candidate metadata and organizes human review
queues. Research Brain may read a saved Content Scout artifact for conservative
topic alignment, but it does not modify that artifact.

The `content_scout_handoff` contains topics, keywords, categories, review
questions, rights reminders, and notes. Its `apply_automatically` value is always
`false` in V1.

## Research Brain vs. Trend Watcher

Research Brain V1 does not monitor platforms or verify current trends. It does
not use the existing Olympus trend-provider path. A future Trend Watcher may
compare approved research topics with separately obtained trend evidence, but
that is outside this module.

## Inputs

Supported source types are:

- `txt`
- `md`
- `csv`
- `json`
- `manual`
- `pasted_text`
- `test_synthetic`

Local import paths must point to existing files with a supported extension.
URL-like paths are rejected. Each file is limited to 1 MB, and processing is
bounded before contracts are created.

## Import Formats

TXT and Markdown files become one research source each.

CSV accepts flexible fields including `title`, `text`, `content`, `summary`,
`description`, `source`, `author`, `date`, `tags`, `categories`,
`rights_notes`, and `notes`. Invalid rows are rejected individually while valid
rows continue.

JSON accepts either a top-level list or an object containing `sources`. Manual
records use the same flexible fields. Pasted text may be supplied as strings or
objects.

Empty sources are rejected with warnings. Unsupported file types fail clearly.

## Research Sources

Each accepted `BobaResearchSourceV1` includes:

- a stable source ID and source type;
- a user-facing label and title;
- optional author and publication metadata;
- compact topic tags;
- optional rights and user notes;
- a generated compact content summary;
- bounded evidence snippets; and
- warnings and limitations.

The persisted artifact does not retain a full imported document or transcript.

## Insight Extraction

`BobaResearchInsightV1` records a type, summary, source IDs, bounded evidence,
possible content opportunity, risk, confidence, and human-verification state.
V1 can emit:

- topic;
- audience pain;
- audience desire;
- controversy;
- tension;
- story angle;
- hook angle;
- format idea;
- caution; and
- verification needed.

Frequency and keyword matches are local evidence only. They do not establish
market demand, factual truth, or trend status.

## Evidence Rules

Each evidence snippet:

- references its research source;
- is limited to 300 characters;
- includes topic tags, a sentence hint, confidence, and a usage warning; and
- warns against republication without context and rights review.

At most three snippets are retained from a normalized source. Export preserves
bounded evidence while removing local paths, rights notes, and user notes.

## Shorts Ideas

Ideas combine source-linked insights with optional Creator Learning and Content
Scout signals. Creator preferences may influence a format conservatively; they
do not override safety or produce automatic actions.

Idea wording identifies each result as a possible direction. Every idea keeps
source IDs, bounded evidence, risk, confidence, and
`human_review_required=true`. No view, virality, audience-response, or
performance claim is invented.

## Safety Review

The safety review surfaces:

- weak evidence;
- unverifiable or absolute claims;
- copied or copyrighted-content cautions;
- sensitive-topic cautions;
- unknown or blocked rights;
- human-verification notes; and
- blockers.

These are heuristic warnings, not legal, medical, financial, factual, or
copyright determinations. Human review remains required.

## Content Scout Handoff

The handoff includes recommended topics and keywords, possible content
categories, avoid topics, rights reminders, review questions, and Scout notes.
It is a future-facing advisory input only. Research Brain V1 does not mutate
Content Scout, start ingestion, or process media.

## Export and Reset

The safe export removes:

- local import paths;
- rights and usage notes;
- user notes;
- raw source content;
- full transcripts;
- media;
- credentials and secrets.

Reset deletes only the project Research Brain V1 artifact. Content Scout,
Creator Learning, Approval/Rejection Learning, Performance Feedback, and memory
remain unchanged.

## Artifact Path

The project artifact is stored at:

```text
work/boba/projects/<project_id>/research_brain/index.json
```

The configured BOBA root may differ in tests or local deployments, but the
project-relative suffix is stable.

## API

```text
POST   /api/v1/boba/projects/{project_id}/research-brain
GET    /api/v1/boba/projects/{project_id}/research-brain
GET    /api/v1/boba/projects/{project_id}/research-brain/export
DELETE /api/v1/boba/projects/{project_id}/research-brain
```

POST accepts manual sources, pasted text entries, local import paths, a source
label, and `dry_run`. A dry run returns the result without persistence.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_research_brain.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_research_brain.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_research_brain.py --project-id PROJECT_ID
```

Default reports are written under
`work/validation_reports/boba_research_brain/` and must not be committed.

## Limitations

Research Brain V1:

- uses local/user-provided research only;
- does not scrape platforms or websites;
- does not fetch URLs;
- does not download media;
- does not call external APIs;
- does not verify real-time trends;
- does not independently verify factual claims;
- does not determine copyright or permission safety;
- does not dump full copyrighted material;
- does not guarantee performance; and
- does not replace human editorial, factual, rights, or safety review.
