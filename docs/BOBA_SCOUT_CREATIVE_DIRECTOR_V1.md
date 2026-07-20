# BOBA Scout + Creative Director V1

## Purpose

BOBA Scout + Creative Director V1 adds an advisory intelligence layer on top of Olympus
Internal RC1. It helps a user evaluate manually supplied video ideas and turn existing Olympus
analysis, story, virality, planning, and editing metadata into compact clip briefs.

It does not download videos, inspect remote media, trigger rendering, publish content, or establish
copyright safety.

## BOBA Scout

Scout accepts metadata supplied through the BOBA API or a local JSON/CSV import. Candidate metadata
can describe a manual link, manual metadata, or metadata previously obtained from an official API.
Olympus does not call an official API in this version.

Scout scores:

- title curiosity and hook potential;
- emotional potential;
- novelty;
- topic clarity;
- likely clipping density and duration suitability;
- rights and permission risk.

Scoring is deterministic, local, and metadata-only. A high score means the idea matched the
implemented criteria; it is not a prediction or guarantee of virality.

## Creative Director

Creative Director reads available Olympus facts, including:

- bounded transcript segments;
- `analysis_signals_v2`;
- Story V2 metadata;
- virality and planning metadata;
- editing timelines;
- explicit BOBA memory lessons.

For each selected plan it persists a `BobaCreativeBriefV1` with a target emotion, hook type,
curiosity trigger, story angle, recommended duration, pacing, caption style, motion style, music
mood, editing notes, risk warnings, and an explanation of why the angle may work.

Music guidance is a mood label only. BOBA does not select copyrighted songs or tracks.

## Rights And Permission Gate

Every candidate has a rights status and a separate user confirmation flag. Processing status is
allowed only when:

1. the user explicitly confirms permission; and
2. the rights status is `user_owned`, `permission_confirmed`, or `licensed`.

Candidates with unknown rights remain ideas or require rights review. Candidates marked
`not_allowed` cannot be approved. Approval endpoints only update local BOBA state and memory; they
do not start an Olympus workflow.

This is a technical consent gate, not legal advice and not a copyright-safety determination.

## Manual Candidate Workflow

Create metadata manually:

```http
POST /api/v1/boba/candidates
Content-Type: application/json

{
  "candidate_id": "candidate_focus_idea",
  "source_type": "manual_link",
  "title": "Why focus fails when motivation is high",
  "url": "https://example.com/video",
  "creator": "Example Creator",
  "duration_seconds": 480,
  "metadata": {"topic": "focus", "emotional_potential": 0.7},
  "rights_status": "unknown",
  "permission_confirmed": false,
  "status": "idea_only"
}
```

Then score and review it:

```text
POST /api/v1/boba/candidates/{candidate_id}/score
POST /api/v1/boba/candidates/{candidate_id}/approve
POST /api/v1/boba/candidates/{candidate_id}/reject
GET  /api/v1/boba/candidates
```

`BobaScout.import_candidates(path)` supports local `.json` and `.csv` files up to 2 MB. It performs
no network request.

## Approval Learning

Candidate and clip-idea approvals are explicit events. BOBA stores a bounded trait-level lesson in
the existing local BOBA Memory store. It does not store media, transcripts, credentials, or passive
viewing behavior.

- Candidate approvals and rejections apply small bounded adjustments to future metadata scoring.
- Clip-idea approvals and rejections store bounded hook, pacing, caption, motion, and music-mood
  preferences.
- Every lesson identifies `explicit_boba_approval` as its source.
- A user-supplied reason is optional and is sanitized by BOBA Memory.

## Creative Brief API

```text
POST /api/v1/boba/projects/{project_id}/creative-briefs
GET  /api/v1/boba/projects/{project_id}/creative-briefs
POST /api/v1/boba/projects/{project_id}/creative-briefs/{clip_id}/approve
POST /api/v1/boba/projects/{project_id}/creative-briefs/{clip_id}/reject
```

Brief generation reads persisted Olympus artifacts and writes BOBA JSON only. It never calls the
renderer.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_scout_creative_director.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_scout_creative_director.py --synthetic-candidates
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_scout_creative_director.py --synthetic-project
```

Reports are written under `work/validation_reports/boba_scout_creative_director/` and remain ignored
by Git.

## What This Version Does Not Do

- It does not autonomously browse or scout the internet.
- It does not call external APIs by default.
- It does not download YouTube or other platform media.
- It does not use cookies, login sessions, private videos, or restriction bypasses.
- It does not automatically process an external source.
- It does not establish ownership, licensing, fair use, or copyright safety.
- It does not guarantee that a candidate or clip will perform well.
- It does not force planning, editing, rendering, or publishing decisions.

## Limitations

- Scouting quality is limited to the metadata supplied by the user.
- Official API adapters are not included; `official_api_metadata` only identifies already supplied
  metadata.
- Creative briefs depend on the availability and quality of existing Olympus artifacts.
- Approval learning is deliberately conservative and local; one decision produces only a bounded
  adjustment.
- No real external media or audience-performance data is used by the synthetic validator.
