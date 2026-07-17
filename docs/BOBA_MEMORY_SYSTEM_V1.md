# BOBA Memory System V1

BOBA Memory V1 is Olympus's local, transparent long-term intelligence layer. It records
bounded project lessons, explicit creator preferences, and safe pattern-level global
principles so BOBA can explain what it remembered before making advisory decisions.

BOBA Memory is not an autonomous agent, analytics engine, internet crawler, cloud profile,
copyright archive, or guarantee of better performance. Existing Olympus engines still plan,
edit, render, validate, and publish their own artifacts.

## Architecture

The repository already had `src/olympus/boba/memory.py` and a flat BOBA module layout.
Memory V1 therefore extends that layout instead of introducing a competing `memory/` package:

- `memory_contracts.py` defines stable JSON-safe contracts.
- `memory_validation.py` blocks secret-like, binary, media-path, transcript, lyric, caption,
  and large copied-text payloads.
- `store.py` remains the single BOBA persistence implementation and now supports all three
  long-term scopes in addition to BOBA Core state.
- `project_memory.py`, `creator_memory.py`, and `global_memory.py` build bounded summaries.
- `memory_retrieval.py` performs deterministic local retrieval.
- `memory_learning.py` accepts explicit feedback and validation reports only.
- `memory_application.py` translates retrieved records into bounded BOBA advice.
- `memory_summarizer.py` centralizes bounded excerpts and ranges.
- `memory_migration.py` migrates the old bounded BOBA project summary when possible.

The flow is:

```text
Olympus/BOBA project signals -> Project Memory records
Explicit creator feedback    -> Creator Memory records
Local principles             -> Global Memory records
Memory query                 -> Ranked bounded records
Retrieved records            -> BOBA advisory application
```

## Memory Scopes

### Project Memory

Project Memory records what happened in one Olympus project:

- source topic and bounded story summaries;
- known speaker roles when available;
- selected and rejected clip identifiers;
- source ranges already used;
- unused story opportunities;
- BOBA decisions;
- safety warnings;
- known render and validation limitations.

It never persists the full transcript, complete captions, scripts, downloaded media, or
rendered media. The builder works with partial projects and records missing evidence honestly.

The following known risks remain visible in project summaries until separately validated:

- canonical render checkpoint compatibility with `render/<project_id>/run/index.json`;
- user-reported A/V voice delay;
- user-reported abrupt clip cuts;
- unproven real face-tracked motion;
- unverified music audibility and speech clarity;
- unavailable Git history in the current extracted workspace.

BOBA Memory does not fix or conceal these issues.

### Creator Memory

Creator Memory is built from Creator Personalization V2 profiles and explicit feedback only.
It can summarize:

- preferred and avoided clip traits;
- hook, title, caption, music, and motion preferences;
- preferred and banned hashtags;
- known good and bad patterns;
- feedback count and gradual confidence.

Learning is conservative. One feedback item cannot create a large scoring change. Repeated
feedback can raise confidence gradually. Passive viewing, hidden clicks, inferred private
traits, and unrelated user data are never learning inputs.

### Global Memory

Global Memory V1 is seeded locally from the BOBA constitution and Olympus's safe pattern-level
guidance. It contains high-level hook, retention, editing, caption, music, motion, metadata,
and safety principles.

It does not crawl the internet, copy creator titles, retain source documents, store scripts or
lyrics, or claim current trend intelligence. Live/cached trend research remains a separate
Olympus subsystem with its own truth metadata.

## Contracts

The public Memory V1 contracts are:

- `BobaMemoryRecordV1`
- `BobaProjectMemoryV1`
- `BobaCreatorMemoryV1`
- `BobaGlobalMemoryV1`
- `BobaMemoryQueryV1`
- `BobaMemoryRetrievalResultV1`
- `BobaMemoryApplicationV1`

Every record has a scope, record type, bounded summary/evidence, confidence, importance,
decay rate, tags, target systems, warnings, and explicit source identity. Project and creator
records require their matching identifiers.

`memory_application_v1` is attached to BOBA decisions, candidate rankings, and editorial
policies when memory was consulted. It lists the memory IDs used, bounded adjustments,
confidence, explanation, and warnings. It is advisory metadata; it never claims an Olympus
render effect was applied.

## Safety and Privacy

Before save or import, Memory V1 validates:

- secret-like keys and text;
- API keys, passwords, cookies, bearer tokens, GitHub tokens, Slack tokens, and OpenAI-style
  key prefixes;
- large transcript/script/document-like payloads;
- lyric/caption-like multi-line payloads;
- absolute media and binary paths stored as content;
- binary values;
- record scope and type;
- identifier format;
- confidence and importance bounds;
- excerpt length;
- export byte size.

Unsafe content fails with a clear validation error. Short excerpts are normalized and bounded
to the configured limit. No memory is synchronized outside the local workspace.

Memory does not prove that a source, asset, or output is copyright-safe. Rights and upload
review remain separate Olympus responsibilities.

## Local Storage

The default long-term root is `work/boba/memory/`:

```text
work/boba/memory/
  projects/<project_id>/project_memory.json
  projects/<project_id>/records.json
  creators/<profile_id>/creator_memory.json
  creators/<profile_id>/records.json
  global/global_memory.json
  global/records.json
  indexes/by_scope.json
  indexes/by_project.json
  indexes/by_creator.json
  indexes/by_tag.json
  exports/
  backups/
```

Writes use a temporary sibling file, flush, `fsync`, and Windows-safe `os.replace`. Files have
schema versions and size limits. Corrupted JSON raises a clear error instead of silently
discarding memory. Reset moves the scoped directory into `backups/` before rebuilding indexes.

BOBA Core Brain state remains in its existing `work/boba/projects/<project_id>/` layout. This
preserves compatibility while the new long-term records live under `work/boba/memory/`.

## Retrieval

Memory V1 uses deterministic retrieval; no vector database or external dependency is needed.
Ranking considers:

- scope and exact project/creator identity;
- target system;
- tags and clip traits;
- content niche;
- confidence and importance;
- recency and optional decay;
- record type;
- configured result limit and confidence floor.

Creator records are never returned for a different creator profile. Project records are limited
to the requested project. Cross-project reuse occurs through explicit creator memory or safe
global pattern records, not by exposing another project's raw summary.

## Learning

Supported learning inputs are:

- explicit Creator Personalization feedback;
- accepted/rejected clip labels submitted by the user;
- explicit notes;
- validation reports;
- known failure/success notes;
- project-outcome placeholders that explicitly state analytics are unavailable.

Validation success does not become an audience-performance claim. Analytics learning is not
implemented. The configuration permanently disables passive-view learning.

## Advisory Application

Memory V1 can create bounded advice for:

- ranking: prefer an explicitly requested emotional payoff when the story is complete;
- ranking: warn when a source range was already used;
- upload metadata: warn against generic titles;
- music: recommend a speech-first lower-intensity mix after repeated explicit feedback;
- motion: recommend stable center fallback when face evidence is unavailable/unproven;
- editorial policy: preserve the payoff tail.

Ranking score adjustments are capped and remain inside BOBA's advisory ranking. Memory does not
directly override Olympus Planning, Editing, Rendering, Safety, or Upload Metadata engines in V1.

## API

All routes are local and versioned under `/api/v1/boba`:

- `GET /memory/projects/{project_id}`
- `POST /memory/projects/{project_id}/build`
- `GET /memory/creators/{profile_id}`
- `POST /memory/creators/{profile_id}/build`
- `GET /memory/global`
- `POST /memory/global/build`
- `POST /memory/query`
- `POST /memory/feedback`
- `GET /memory/export`
- `POST /memory/import`
- `POST /memory/reset`

Import and reset require explicit confirmation. Reset responses expose only the local backup
name, not an absolute filesystem path. API payloads use the same safety validation as direct
store calls.

Existing `/personalization/feedback` submissions are also passed to Memory V1 through an
explicit callback when Memory V1 is enabled. Tests or custom service instances without that
callback remain backward-compatible.

## Frontend

The Results page adds a compact BOBA Memory panel showing:

- bounded project summary;
- selected/rejected counts;
- used source-range count;
- unused opportunities;
- visible known limitations;
- creator style summary;
- explicit feedback count and confidence;
- learned/avoided patterns;
- memory record count.

Rendered clip BOBA reasoning also reports how many bounded memory records influenced the
advisory. The frontend never shows raw long text or claims that memory is complete or perfect.

## Configuration

Environment variables use the `OLYMPUS_BOBA_MEMORY__` prefix. Important defaults are:

```text
ENABLED=true
STORAGE_DIR=work/boba/memory
LOCAL_ONLY=true
MAX_EXCERPT_CHARS=300
EXPLICIT_FEEDBACK_ONLY=true
ALLOW_CREATOR_MEMORY=true
ALLOW_GLOBAL_MEMORY=true
ALLOW_IMPORT_EXPORT=true
BACKUP_BEFORE_RESET=true
REJECT_SECRET_LIKE_TEXT=true
REJECT_LARGE_COPYRIGHTED_TEXT=true
RETRIEVAL_LIMIT_DEFAULT=20
MIN_CONFIDENCE_DEFAULT=0.2
MEMORY_DECAY_ENABLED=true
AUTO_LEARN_FROM_VALIDATION_REPORTS=true
AUTO_LEARN_FROM_PASSIVE_VIEWING=false
```

## CLI Validation

Run with the repository virtual environment:

```powershell
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_memory.py --self-check
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_memory.py --simulate-project
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_memory.py --simulate-creator
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_memory.py --simulate-global
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_memory.py --simulate-feedback
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_memory.py --simulate-query
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_memory.py --simulate-export-import
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_memory.py --project-id PROJECT_ID
```

Reports are written to:

- `work/validation_reports/boba_memory/boba_memory_validation_report.json`
- `work/validation_reports/boba_memory/boba_memory_validation_summary.md`

Existing-project mode reads Olympus artifacts and writes bounded memory only. It does not
download, render, rerender, play, or modify media.

## Reset, Export, and Import

Exports contain schema-versioned JSON only. Full exports include all scoped records and summary
objects. Scoped exports can target one project or creator. Imports revalidate every record and
summary before save and reject unsupported schemas.

Reset is destructive only to the chosen active Memory V1 scope and creates a timestamped local
backup first by default. BOBA Core state, personalization profiles, source media, rendered media,
and Olympus stage artifacts are not deleted.

## Current Limitations

- No cloud sync.
- No hidden or passive learning.
- No audience analytics learning yet.
- No autonomous web crawling.
- No vector database or semantic embedding retrieval.
- No guarantee of improved performance.
- No copyrighted-content archive.
- No proof that A/V sync, abrupt cuts, face tracking, music audibility, or rendering quality are
  fixed.
- No automatic direct override of Olympus engines.
- Global Memory V1 is seeded, not live trend intelligence.
- Git history remains unavailable while the extracted `.git` directory is empty.

## Future Upgrades

Future phases may add user-approved analytics outcomes, richer experiments, opt-in semantic
retrieval, memory editing tools, and carefully bounded engine-consumption contracts. Those
features must preserve local transparency, explicit consent, copyright safety boundaries, and
honest applied-versus-advisory metadata.
