# BOBA Experimentation System V1

## 1. Purpose

BOBA Experimentation System V1 turns saved BOBA recommendations into compact,
testable creative experiment plans. It helps a creator compare one bounded
creative variable at a time while preserving source evidence, uncertainty,
risk, and explicit approval requirements.

V1 is local, deterministic, JSON-safe, and advisory.

## 2. What The System Does

The system can propose baseline-versus-variant reviews for:

- hook direction;
- caption treatment;
- motion intensity;
- music mood;
- SFX intensity;
- the opening three seconds;
- retention or payoff treatment;
- clip-brief clarity.

It rejects unsupported or unsafe ideas instead of inventing a variant.

## 3. Relationship To Learning Systems

Creator Learning Loop remains the source of explicit creator preferences.
Approval / Rejection Learning remains the source of derived decision patterns.
Experimentation reads those artifacts as bounded guidance but does not mutate
them.

An explicit manual experiment result can request a future learning handoff.
That request is recorded only; V1 does not update learning automatically.

## 4. Inputs

V1 can consume saved:

- Clip Brief Generator output;
- Hook + Retention analysis;
- Caption + Motion recommendations;
- Music Mood recommendations;
- Creative Director V2 direction;
- Editorial Decision output;
- Explanation Engine output;
- Creator Learning output;
- Approval / Rejection Learning output;
- compact BOBA project memory.

Missing optional inputs degrade through signal-usage warnings. At least one
candidate-level recommendation is needed to create an evidence-backed plan.

## 5. Experiment Plan Structure

Each plan carries:

- stable project, candidate, brief, target, and experiment IDs;
- experiment type and status;
- a traceable baseline;
- one to three compact variants;
- a hypothesis;
- a metric plan;
- success criteria;
- a risk review;
- a future learning handoff;
- creator approval requirements;
- confidence, warnings, and limitations.

Plans default to `needs_creator_approval`.

## 6. Baseline And Variants

The baseline names its source artifact and source field. Variants change one
declared variable within an experiment. Hook variants do not also change
captions, motion, audio, or source boundaries; the same isolation rule applies
to every experiment category.

Variants describe a manual creative comparison. They do not claim that an
alternative will outperform the baseline.

## 7. Hypotheses

A hypothesis states:

- the isolated creative question;
- why saved evidence supports testing it;
- the expected review area;
- confidence;
- assumptions needed for a fair comparison.

Hypotheses are testable propositions, not audience predictions or guaranteed
performance claims.

## 8. Metric Plan

V1 uses manual review metrics such as creator preference, hook quality,
retention quality, caption readability, motion safety, and audio fit.

Future viewer-retention or engagement fields are handoff metadata only. When
present, `analytics_required_later=true`. V1 does not collect viewer analytics,
watch time, clicks, or hidden behavior.

## 9. Success Criteria

A variant succeeds only after an explicit creator preference, a sufficient
manual rating, and clearance of relevant risk blockers. A baseline preference,
low rating, new safety issue, or no clear winner is a valid non-success result.

No winner is applied automatically.

## 10. Risk Review

Risk review covers:

- rights and licensing;
- clarity and over- or under-editing;
- misleading hooks;
- caption overload;
- face, framing, and motion safety;
- mood mismatch;
- speech clarity.

High-risk hook alternatives, unresolved track-level rights ideas, unsafe motion
ideas, unsupported variants, and multi-variable ideas are rejected or blocked
for human review.

## 11. Approval Requirements

Every plan requires creator approval before it can be treated as active.
Additional requirements are added for rights, safety, or human editorial
review. Approval metadata does not start an experiment, render media, select a
track, or upload content.

## 12. Manual Results

The optional manual result records:

- experiment and selected baseline/variant IDs;
- a manual rating;
- an explicit creator note;
- an outcome label;
- whether the creator requests a future learning handoff.

Manual results are not analytics. They do not auto-apply a winner. Creator
notes are excluded from compact export.

## 13. Export And Reset

Export returns compact plans and note-free manual results. It excludes media
files, full source text, credentials, and viewer analytics.

Reset deletes only the project's experimentation plan and manual result log.
It preserves Creator Learning, Approval / Rejection Learning, BOBA Memory, and
all other project artifacts.

Dry-run generation returns a plan without writing it.

## 14. Artifact Path

The atomic plan artifact is:

```text
work/boba/projects/<project_id>/experimentation/index.json
```

Explicit manual results, when used, are stored beside it in
`experimentation/results.jsonl`. The configured BOBA root may differ, but the
project-relative suffixes are stable.

## 15. API And Validator

API routes:

```text
POST   /api/v1/boba/projects/{project_id}/experimentation
GET    /api/v1/boba/projects/{project_id}/experimentation
GET    /api/v1/boba/projects/{project_id}/experimentation/export
DELETE /api/v1/boba/projects/{project_id}/experimentation
POST   /api/v1/boba/projects/{project_id}/experimentation/results
```

`POST` accepts `creator_id` and `dry_run`. The result route accepts explicit
manual input only.

Validator:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_experimentation.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_experimentation.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_experimentation.py --project-id PROJECT_ID
```

Generated reports stay under:

```text
work/validation_reports/boba_experimentation/
```

Reports are ignored artifacts and must not be committed.

## 16. Limitations

V1:

- creates plans only;
- does not render or produce experiment media;
- does not upload or download content;
- does not call external APIs;
- does not collect viewer analytics;
- does not learn from hidden behavior;
- does not select copyrighted music tracks;
- does not bypass rights review;
- does not guarantee performance or virality;
- does not automatically apply experiment winners;
- does not replace creator or human editorial review.
