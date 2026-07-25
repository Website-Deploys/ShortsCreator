# BOBA Approval / Rejection Learning V1

## 1. Purpose

BOBA Approval / Rejection Learning V1 converts deliberate creator approvals,
rejections, ratings, corrections, chosen alternatives, preference notes, and
manual tags into bounded decision-learning metadata. It explains what BOBA
likely got right or wrong, attributes feedback to evidence-backed modules, and
produces advisory guidance for future review.

The system is deterministic, local, JSON-safe, and project-scoped.

## 2. Difference From Creator Learning Loop

Creator Learning Loop stores the explicit feedback event log and derives a
general creator preference profile. Approval / Rejection Learning does not
replace or duplicate that system.

Approval / Rejection Learning:

- reads the existing explicit Creator Learning events;
- links each usable event to saved BOBA decision artifacts;
- creates approval and rejection cases;
- attributes likely module ownership;
- maps bounded corrections;
- scores repeated and contradictory decision patterns;
- stores a separate derived project artifact.

Creator Learning remains the single source of truth for submitted feedback
events.

## 3. Feedback Inputs Used

V1 uses only deliberate Creator Learning event types:

- `approval`
- `rejection`
- `rating`
- `correction`
- `chosen_alternative`
- `preference_note`
- `manual_tag`

Neutral or unclear feedback remains ambiguous. It does not become an approval
or rejection case, and its attribution can remain `unknown`.

V1 does not collect clicks, watch time, hover behavior, abandoned actions, or
other hidden/passive UI behavior.

## 4. Approval Case Learning

An approval case connects an explicit positive event to a candidate or BOBA
artifact when available. It records:

- the approved target and candidate identity;
- bounded positive factors;
- what BOBA appears to have gotten right;
- source-field evidence;
- a provisional reusable pattern;
- confidence, warnings, and limitations.

An approval is evidence of creator preference. It is not evidence of audience
performance or guaranteed success.

## 5. Rejection Case Learning

A rejection case connects an explicit negative event to saved BOBA artifacts
when available. It records:

- likely rejection causes;
- what BOBA appears to have gotten wrong;
- evidence from the submitted note/tags and saved artifact risks;
- correction mappings;
- future avoidance guidance;
- confidence, warnings, and limitations.

Examples include slow openings, excessive zoom, mood mismatch, missing payoff,
low creator interest, unclear explanations, caption readability problems, and
speech-clarity risks.

## 6. Decision Attribution

Attribution uses only bounded evidence:

1. explicit feedback `target_type`;
2. submitted note and tags;
3. a matching target ID in saved BOBA artifacts;
4. artifact warnings, risks, recommendation fields, and explanation evidence.

Supported module labels are:

- `candidate_discovery`
- `clip_ranking`
- `editorial_decision`
- `creative_director`
- `clip_brief`
- `hook_retention`
- `caption_motion`
- `music_mood`
- `explanation`
- `creator_learning`
- `unknown`

If multiple modules have equally strong evidence and the target does not
identify an owner, V1 reports `unknown` rather than inventing responsibility.

## 7. Correction Mapping

Negative factors can produce a bounded correction mapping containing:

- the problem category;
- the affected module;
- a suggested correction;
- a future rule hint;
- strength and confidence;
- `apply_automatically=false`.

Correction mappings are recommendations for review. They never mutate ranking,
editorial, creative, editing, or rendering decisions.

## 8. Pattern Scoring

V1 aggregates equivalent factors into:

- `repeated_approval`
- `repeated_rejection`
- `contradiction`
- `weak_signal`
- `strong_signal`

Repeated consistent feedback raises pattern strength. A single event remains a
weak signal. Contradictory explicit feedback is retained and reduces
confidence; it is not silently resolved in either direction.

## 9. Module Guidance

Advisory guidance is grouped for:

- ranking and candidate discovery;
- editorial decisions;
- creative direction;
- clip briefs;
- hook and retention;
- captions and motion;
- music mood, SFX, and speech handling;
- explanations;
- general human review.

Both module guidance and correction mappings always default to
`apply_automatically=false`.

## 10. Confidence And Contradictions

Confidence is based on explicit event polarity, target resolution, bounded
factor evidence, repetition, and attribution ambiguity. It is reduced when:

- the target artifact is missing;
- only a general note is available;
- multiple modules could be responsible;
- feedback conflicts with earlier explicit feedback.

Confidence is advisory and must not be interpreted as a performance
probability.

## 11. Export And Reset

The export endpoint returns compact decision-learning metadata. Raw feedback
notes and evidence snippets are omitted from the export, and media, secrets,
and full transcripts are not included.

Reset deletes only the Approval / Rejection Learning artifact. It preserves:

- Creator Learning `events.jsonl`;
- the Creator Learning profile;
- project, creator, and global BOBA Memory;
- all other BOBA artifacts.

Dry-run generation does not persist the derived artifact or any new memory.

## 12. Artifact Path

The atomic local artifact is:

```text
work/boba/projects/<project_id>/approval_rejection_learning/index.json
```

The configured BOBA store root may differ, but the project-relative suffix is
stable.

## 13. API And Validator Commands

API routes:

```text
POST   /api/v1/boba/projects/{project_id}/approval-rejection-learning
GET    /api/v1/boba/projects/{project_id}/approval-rejection-learning
GET    /api/v1/boba/projects/{project_id}/approval-rejection-learning/export
DELETE /api/v1/boba/projects/{project_id}/approval-rejection-learning
```

`POST` accepts `creator_id` and `dry_run`. It does not render or call external
services.

Validator:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_approval_rejection_learning.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_approval_rejection_learning.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_approval_rejection_learning.py --project-id PROJECT_ID
```

Validation reports are generated under:

```text
work/validation_reports/boba_approval_rejection_learning/
```

Reports are generated artifacts and must not be committed.

## 14. Limitations

- V1 learns only from explicit submitted feedback.
- It does not collect hidden behavior.
- It does not use viewer analytics.
- It does not call external APIs.
- It does not download or render media.
- It does not guarantee engagement, virality, or performance.
- It does not prove which module caused a creator decision.
- It does not automatically apply guidance.
- It does not replace human review.
