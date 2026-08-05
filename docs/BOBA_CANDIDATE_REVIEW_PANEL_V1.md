# BOBA Candidate Review Panel V1

The specialized human review surface for candidate clips discovered by Olympus,
built as a mode within the existing BOBA Frontend / Review UI.

## 1. Purpose

Let a reviewer see every candidate clip, understand why it was discovered,
inspect its original rank and score evidence, preview its exact time window,
read transcript context, review creative reasoning, compare candidates,
identify overlapping windows, and route confirmed human actions to the module
that owns them — while preserving a complete canonical review history.

## 2. Authority boundary

The panel **may own**: the selected candidate in the current session, a
temporary comparison selection, filters, sort, review-session metadata, read
markers, bounded reviewer notes before submission, confirmation-dialog state,
canonical request routing, immutable receipts, display-only categories,
side-by-side projections, and overlap computed from exact persisted ranges.

The panel **must not own**: candidate discovery, rank, score, editorial
selection, workflow stage completion, approval validity, Rights decisions,
Safety decisions, technical validation, output-quality acceptance, artifact
integrity, Final Decision Bus readiness, or publication eligibility.

Correct: “Clip Ranking ranked this candidate #2.”
Incorrect: “This is the second-best possible clip.”

## 3. Review UI integration

Mounted through the existing project results route alongside
`BobaReviewWorkspace`. No second general-purpose Review UI and no second
router. It reuses the Review UI digest and sanitisation primitives, protected
preview helper, source-card presentation, error classifier, confirmation
pattern, stale-state handling and receipt semantics.

## 4. Candidate sources

Thirteen fixed sources, each read through a fixed store loader:

| Source | Authority domain | Kind |
| --- | --- | --- |
| `clip_discovery` | candidate_discovery | authoritative (**required**) |
| `clip_ranking` | candidate_rank | authoritative |
| `editorial_decision` | editorial_selection | authoritative |
| `explanation` | explanation | advisory |
| `clip_brief` | creative_brief | advisory |
| `hook_retention` | hook_retention | advisory |
| `caption_motion` | caption_motion | advisory |
| `music_mood` | music_mood | advisory |
| `rights_permission_gate` | rights | authoritative |
| `safety_gate` | safety | authoritative |
| `workflow_controller` | workflow | authoritative |
| `artifact_inspector` | artifacts | authoritative |
| `validator_runner` | validation | authoritative |

A missing source reports `unavailable` and is **never** treated as a pass.

## 5. Candidate identity

Candidates come from `BobaCandidateClipV1` inside
`boba_candidate_clip_discovery_v1`. The identity field is `candidate_id`. Rows
whose `project_id` does not match are excluded. Candidate records carry **no
revision identity**, so `candidate_revision_id` is always absent, and there is
**no explicit supersession field** in any owner record — `superseded` and
`historical` are therefore reported as explicit flags that currently stay
false rather than being inferred.

## 6. Exact source time ranges

`start_seconds`, `end_seconds` and `duration_seconds` are float seconds copied
verbatim. All arithmetic rounds to 3 decimals (millisecond precision) to remove
binary float noise deterministically without ever widening or narrowing a
window. A contract validator rejects any reference where `end <= start` or
where `duration` does not match the persisted range.

## 7 & 8. Candidate queue and priority

Twelve fixed presentation tiers:

| Tier | Reason |
| --- | --- |
| 10 | Selected candidate with a critical Rights or Safety block |
| 20 | Requires an exact human selection decision |
| 30 | Conflicting editorial records |
| 40 | Missing required discovery or rank evidence |
| 50 | Stale canonical evidence |
| 60 | Source-shortlisted by Editorial Decision |
| 70 | Strong original rank without a human decision |
| 80 | Substantial overlap requiring comparison |
| 90 | Current candidate in source-owned rank order |
| 100 | Rejected current candidate |
| 110 | Superseded candidate |
| 120 | Historical candidate |

Ties break on a total sort key: `tier : original rank : start seconds :
creation index : candidate id`. Frontend arrival order is never used, and there
is no generated priority score.

## 9 & 10. Rank and score definitions

Rank is owned by **Clip Ranking** (`rank`, integer ≥ 1). Scores keep their
owner, scale, definition and direction:

| Owner | Score | Scale |
| --- | --- | --- |
| Candidate Clip Discovery | `confidence`, `standalone_score` | 0.0 – 1.0 |
| Clip Ranking | `total_score` + 13 components | 0 – 100 |
| Editorial Decision | `editorial_confidence` | 0.0 – 1.0 |

Because discovery and ranking use **different scales**, cross-module scores are
flagged as not directly comparable. Penalty components
(`context_risk_score`, `repetition_penalty`, `overlap_penalty`,
`rights_safety_penalty`) are marked `lower_is_better`.

`total_score` is labelled `source_owned_composite` because Clip Ranking owns it.
The panel creates **no** composite of its own. Component weights are not
persisted by the owner, so **no weight is displayed**. Ties are reported when
two owner `total_score` values are equal. No score is a probability or a
virality prediction.

## 11. Comparison

Two to four candidates, side by side: exact range, duration, discovery reason,
original rank and tier, all score cards with scales, editorial status,
evidence coverage, warnings and limitations. `no_automatic_winner` is a
constant `True`. Duplicate ids collapse; more than four is rejected.

## 12 & 13. Overlap and duplicate windows

```
intersection = max(0, min(a.end, b.end) - max(a.start, b.start))
union        = duration_a + duration_b - intersection
iou          = intersection / union   (0.0 when union == 0)
```

- **exact duplicate window** — both boundaries match within 1e-6
- **substantial overlap** — IoU ≥ **0.60** (fixed, documented threshold)
- **partial overlap** — overlap > 0 but IoU < 0.60
- **contained** — one window fully covers the other

Touching boundaries are not an overlap. Overlap is **time-range overlap only**
(`source_time_overlap_only = true`); it is never a semantic duplication claim,
and overlapping candidates are never rejected automatically.

Clip Ranking already records `overlap_with_candidate_id` and an
`overlap_penalty`; the panel displays those as owner data and computes IoU
separately for presentation.

## 14. Protected preview

Reuses the Review UI same-origin project-scoped media helper. Arbitrary URLs,
absolute paths, UNC paths, `file:` URIs and traversal are refused; local
absolute paths are never exposed. The panel publishes the exact candidate
window so the player can seek to it, and a bounded context window labelled
“Preview context only. This does not change the candidate boundaries.”
No FFmpeg is invoked and no temporary preview media is generated.

Browser playback does **not** prove artifact integrity, source accuracy,
**technical validation**, output quality or Rights clearance.

## 15. Transcript context

Only the transcript snippets persisted on the candidate record are shown,
verbatim, plus the owner's `topic_segment_ids`. Context is bounded to 60
seconds either side and is a display hint only. The panel does not
re-transcribe media, and speaker references remain opaque source-owned
identifiers — no speaker identification, facial recognition, biometric or
emotion inference from frames.

## 16. Creative evidence

Clip Brief, hook and retention reasoning, caption and motion recommendations,
music mood and editorial explanation are shown as **advisory**
(`advisory_only = true`). A creative recommendation is never converted into an
approval.

## 17. Local shortlist versus canonical shortlist

`locally_shortlisted_candidate_ids` is review-session UI metadata, labelled in
the interface as “Review-session shortlist — not an editorial decision.” The
canonical shortlist lives in Editorial Decision's `selected_clip_ids` and
`selected`, and in Clip Ranking's `recommended_clip_ids`.

## 18 & 19. Human actions and confirmation

Six fixed action descriptors. Only two are available in V1, because only they
have a real owning operation:

| Action | Owner | Operation | V1 |
| --- | --- | --- | --- |
| Submit candidate feedback | `creator_learning` | `record_creator_feedback_event` | **available** (advisory) |
| Record candidate review note | `creator_learning` | `record_creator_feedback_event` | **available** (advisory) |
| Select exact candidate | `editorial_decision` | — | **unavailable** |
| Reject exact candidate | `editorial_decision` | — | **unavailable** |
| Request candidate revision | `editorial_decision` | — | **unavailable** |
| Request alternate candidate | `clip_discovery` | — | **unavailable** |

Selection and rejection are unavailable because Editorial Decision exposes no
operation that records a human decision for one exact candidate — its entry
points regenerate the whole editorial set from signals, which would make the
panel a second editorial engine. The existing BOBA
`/candidates/{id}/approve|reject` API operates on **Content Scout source-video
candidates** (`BobaCandidateV1`, with `url` and `rights_status`), a different
record type. No substitute owner was invented.

Submission sequence: refresh snapshot → verify project digest → verify workflow
revision → verify candidate digest → verify every source-record digest → verify
the descriptor is still available → verify owner module and operation → verify
the candidate is still current → show consequences and what the action does not
do → require explicit confirmation and a bounded reason → submit idempotently →
wait for the owner receipt → refresh queries.

## 20. Stale-state protection

| Guard | Code |
| --- | --- |
| Request expired (10 minutes) | `expired_snapshot` |
| Action no longer offered | `action_unavailable` |
| Candidate gone | `candidate_removed` |
| Project digest drifted | `stale_project_snapshot` |
| Workflow revision changed | `workflow_revision_mismatch` |
| Candidate record changed | `candidate_digest_mismatch` |
| Source record changed | `source_record_digest_mismatch` |

Each guard is checked independently and rejects **before** the owner is
contacted.

## 21. Canonical receipts

Immutable, content-checked receipts record the owner module and operation, the
canonical record id and digest, acceptance and any error. `_persist_receipt`
**raises** if `authoritative_state_changed` is set without a canonical owner
record id and digest. Creator Learning feedback is accepted but recorded with
`authoritative_state_changed = false`, because it is advisory. Resubmitting
reuses the existing receipt and contacts the owner exactly once.

## 22 – 25. Integration Layer, Safety Gate, Workflow, Review UI

Nineteen fixed Integration Layer operations under `candidate_review.*`. Safety
Gate classifies eighteen as `automatic_read_only` and `submit_action` as
`approval_required_read_only`. Workflow identity (`workflow_run_id`,
`stage_instance_id`, `revision`) is read from the Workflow Controller's active
run; the panel never requests a transition. Review UI V1 behaviour is unchanged.

## 26. API

Twenty project-scoped routes under
`/api/v1/boba/projects/{project_id}/candidate-review`: root, `registry`,
`sessions` (POST / GET / PATCH / DELETE), `queue`,
`candidates/{candidate_id}` plus `/transcript`, `/overlaps` and `/snapshot`,
`snapshots/{snapshot_id}/refresh`, `compare`, `actions` with `/validate`,
`/submit` and read-back, `timeline`, `events`, and `export`. The Review UI
event stream is reused; no second SSE endpoint was added.

## 27. Persistence

Under `candidate_review/`: `index.json`, immutable `registries/`, `sessions/`,
`snapshots/`, immutable `actions/`, immutable `receipts/`, and bounded
`event_cursors/`. Atomic writes, schema versions, bounded records, no secrets,
no absolute paths. Candidate, ranking, editorial, transcript, media, creative,
workflow, artifact and validation records are referenced by id and digest, never
duplicated. Reset removes only panel metadata and reports every preserved
history explicitly.

## 28. Accessibility

Semantic candidate list, keyboard-selectable candidates, labelled compare
controls and tabs, visible focus, no colour-only status, screen-reader rank and
score-scale labels, modal focus trap with focus return, Escape to close,
reduced-motion support, 44 px touch targets, transcript section headings,
labelled preview controls, errors associated with controls and polite
stale-state announcements.

## 29. Performance

Queue page size 50, at most 500 loaded candidates, at most 4 comparison
candidates, transcript context capped at 60 seconds, 100 timeline entries, 200
overlap records, 100 retained events, memoised overlap and bounded projections.

## 30. Validation

```
python -m ruff check src tests tools
python -m mypy src/olympus/boba tools/validate_boba_candidate_review.py
python -m pytest tests/unit/test_boba_candidate_review.py
python tools/validate_boba_candidate_review.py --self-check
python tools/validate_boba_candidate_review.py --synthetic-project
```

```
cd frontend && npm run typecheck && npm run lint && npm test && npm run build
```

The validator runs 222 named scenarios across twelve groups using only
synthetic metadata built through the real owning contracts.

## 31. Limitations

- **No authoritative candidate action exists in V1.** Selection, rejection,
  revision requests and alternate requests are declared but unavailable.
- Owner records carry no candidate revision identity and no supersession field,
  so revision and supersession are reported as always-absent flags.
- Only transcript snippets already persisted on the candidate record are
  available; there is no segment-level transcript join.
- Candidate preview falls back to the project source, because no per-candidate
  media artifact reference exists at discovery time.
- Overlap is time-range overlap, never semantic duplication.
- Browser playback is not technical validation.
- The panel does not discover or rerank candidates, creates no hidden composite
  score, selects no winner, and claims no production readiness.
