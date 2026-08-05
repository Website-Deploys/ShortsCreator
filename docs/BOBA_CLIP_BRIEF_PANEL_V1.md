# BOBA Clip Brief Panel V1

## 1. Purpose

The Clip Brief Panel is a specialized read-only mode of the BOBA Review UI. It
projects the clip briefs that the Clip Brief Generator persisted, links each
field to the canonical records that justify it, lets a reviewer compare briefs
side by side, and routes a small number of advisory actions to their real owning
module. It is a reading and routing surface, not a second brief generator.

## 2. What it is not

It does not generate, regenerate or rewrite a clip brief. It does not add a field
the owner schema does not define. It does not compute a quality, virality or
composite score. It does not choose a winning brief. It does not approve, reject,
revise or regenerate anything, and it never changes brief state optimistically.

## 3. Owner of the record

`BobaClipBriefV1` in `src/olympus/boba/clip_brief.py` is the only owner of clip
brief content. The panel reads it through `BobaMemoryStore.load_clip_briefs` and
writes nothing back.

## 4. Supported owner schema

The panel supports `brief_version = "boba_clip_brief_generator_v1"`, recorded on
`BobaClipBriefSetV1`. Any other value is flagged: `schema_supported` becomes
false, a warning is attached, completeness becomes `unsupported_schema`, and no
field is interpreted.

## 5. Brief identity

Each projected brief carries the owner's `brief_id`, `candidate_id` and
`ranked_clip_id`, plus the digest of the source record it came from. A brief that
names another project is not projected at all.

## 6. Revision identity is absent, not guessed

`BobaClipBriefV1` defines no revision identity and no supersession field. The
panel therefore reports `brief_revision_id = None`, `superseded = false` and
`superseding_brief_id = None` always. These are never inferred from timestamps,
filenames or ordering.

## 7. No historical archive

The owner persists one current brief set per project. There is no historical
brief archive, so the `historical` and `stale` flags stay explicitly false and
the `historical` and `stale` queue filters return nothing rather than guessing.

## 8. Lifecycle buckets

The owner's `selected_briefs`, `backup_briefs` and `blocked_briefs` lists are
projected verbatim as the `lifecycle_bucket` value `selected`, `backup` or
`blocked`. The panel never moves a brief between buckets.

## 9. Exact source window

`source_window.start_seconds`, `end_seconds` and `duration_seconds` are carried
through unchanged. A reference whose end precedes its start is rejected by the
contract validator rather than being repaired.

## 10. Owner schema field table

`_OWNER_SCHEMA_FIELDS` transcribes `BobaClipBriefV1` field by field: 22 required
paths and 5 optional paths, 27 in total. The table is fixed source code. A
request can never add, remove or reclassify a field.

## 11. No invented field categories

There is deliberately no beats, narrative-arc, ending, audience-segment or
transcript field or section, because the owner model defines none.

## 12. Field projection

Every field projection carries the owner value untouched, its value type, a
digest, whether the owner schema requires it, and whether it is present, empty or
absent. `human_editable` is always false.

## 13. Plain language beside the value

`bounded_explanation` holds the plain-language sentence. It sits beside the owner
value and never replaces, summarises or rewrites it.

## 14. Empty is not absent

A field the owner persisted as an empty list is reported `empty`, not
`unavailable`. A field the owner never persisted is reported `unavailable`. The
two are never merged.

## 15. Advisory guidance is marked

`caption_instruction`, `motion_instruction`, `audio_instruction` and
`sfx_instruction` are marked advisory and carry the limitation that advisory
guidance is not a decision.

## 16. Sections

Nine sections are derived from the owner field table: identity, overview, source
window, hook, story, creative guidance, checklist, warnings and limitations.
Every projected field belongs to exactly one section.

## 17. Completeness means field presence

`complete_for_owner_schema` is true only when every required owner-schema field
is present and the schema is supported. `creative_quality_assessed` and
`technical_quality_assessed` are declared and always false.

## 18. Completeness is not quality

The completeness readout always carries the sentence stating that completeness is
field presence only, and is not creative quality, technical validation, Rights
clearance, Safety approval, approval or render readiness.

## 19. Fixed evidence source registry

Fourteen fixed sources are read through fixed store loaders: clip_brief,
clip_discovery, clip_ranking, editorial_decision, explanation, creative_director,
hook_retention, caption_motion, music_mood, rights_permission_gate, safety_gate,
workflow_controller, artifact_inspector and validator_runner. Only clip_brief is
required.

## 20. Advisory versus authoritative sources

explanation, creative_director, hook_retention, caption_motion and music_mood are
advisory. The rest keep their own authority. An unavailable source record is
reported unavailable and is never treated as a pass.

## 21. Evidence is identity bound

Evidence links are formed only through identities the owning modules persisted:
`candidate_id`, `ranked_clip_id` and the owner's transcript segment identities.
Nothing is inferred from similar text.

## 22. Missing evidence is not a pass

Each missing evidence link carries the limitation stating that missing evidence
is never treated as a pass, and the missing count is reported explicitly.

## 23. Conflicts

A conflict is raised only between records that refer to the same exact identity:
candidate identity, source window, duration, editorial status, lifecycle, clip
identity, duplicate current briefs, and unsupported schema.

## 24. Conflicts are not resolved here

Every conflict is recorded with `resolved = false`, no resolution source, and
`explicit_supersession_found = false`. Confidence is never consulted, and a
blocking conflict withholds the review action instead of being decided.

## 25. Queue priority tiers

Twelve fixed presentation tiers order the queue, from a blocked selected brief
(10) through missing required fields (40) and missing evidence (50) to historical
briefs (120). The tier is a presentation order, not a score.

## 26. Deterministic ordering

Every queue item carries a deterministic sort key built from tier, owner rank,
creation index, start time and brief id. Repeated builds produce identical order.

## 27. Filters and sorts are fixed

Eleven filters and five sorts are supported. Any other value is refused. There is
no quality, virality or predicted-performance sort.

## 28. Comparison

Two to four briefs may be compared. Field, section, completeness, evidence,
source window, duration, warning and limitation comparisons are produced, and
`no_automatic_winner` is pinned to true by the contract. A field missing from one
brief stays visibly missing.

## 29. Preview

The preview reuses the Review UI's existing protected same-origin helper. An
external URL, absolute path, UNC path, file URI or traversal reference is
refused. The persisted window is published unchanged, the context hint is bounded
and labelled non-authoritative, and playback is stated not to be validation.

## 30. Available actions

Only two actions are available in V1, both owned by Creator Learning through
`record_creator_feedback_event`: submit clip brief feedback and record a clip
brief review note. Both are advisory and set
`authoritative_state_changed = false`.

## 31. Unavailable actions

Approve, reject, request revision and request regeneration are declared
unavailable. No canonical operation records a human decision for one exact brief,
and the generator's only entry point rebuilds the whole set, which would make
this panel a second brief generator. Each descriptor states this, and no
substitute owner was invented.

## 32. Stale-state protection

An action request captures the project snapshot digest, workflow revision, brief
digest and per-source record digests. Before submission the panel re-reads
canonical state and refuses on expiry, brief removal, candidate or clip identity
mismatch, or any digest or revision drift. Nothing reaches the owner in that case.

## 33. Receipts

Every submission produces an immutable receipt. `authoritative_state_changed`
cannot be true without a canonical owner record id and digest; the store refuses
such a receipt. A duplicate submission reuses the existing receipt and the owner
is called once.

## 34. Review-session annotations

Reviewer notes live in the review session, bounded to 32 notes of 4,000
characters, refused if they carry credentials, and always labelled
"Review-session annotation — not part of the canonical clip brief."

## 35. Events and timeline

Canonical events are de-duplicated, bounded to 100, and never given invented
progress. A malformed progress pair is dropped. Control events such as heartbeats
are marked as not representing work. When the owner holds more events than are
read, `has_more` says so.

## 36. Integration layer and Safety Gate

Twenty-one operations are registered under `clip_brief_review`, all read-only,
metadata-reset or export. Twenty are classified `automatic_read_only` by the
Safety Gate; `submit_action` is `approval_required_read_only`.

## 37. Reset preserves canonical history

Resetting review metadata removes only the panel's own index, sessions, snapshots
and event cursors. Clip brief records, candidate records, editorial history,
Candidate Review history, Review UI history, workflow history, source media and
accepted outputs are preserved.

## 38. Export

The export links to owner records instead of copying them and declares that
private paths, raw media, raw transcripts and sensitive values are excluded, and
that no brief text was rewritten, no source media modified and nothing uploaded
or published.

## 39. Nothing executes

The module contains no dynamic import, no arbitrary module or operation lookup,
no URL construction, no filesystem path, no network client, no subprocess, shell
or Git invocation, and no FFmpeg or FFprobe invocation. Its only store writes are
its own `boba_clip_brief_review_*` records.

## 40. Frontend placement

`BobaClipBriefReviewPanel` is mounted at all four project results render sites,
after the Candidate Review Panel. The global Review UI workspace, the Candidate
Review Panel and the existing clip brief generator section are all left in place.

## 41. Validation

`tools/validate_boba_clip_brief_review.py` runs 271 catalogued correctness
conditions across fifteen groups plus 27 declared-boundary self-checks, using
synthetic canonical records built through the real owning contracts. It never
touches real media, the network, Git or FFmpeg.

## 42. Test coverage

`tests/unit/test_boba_clip_brief_review.py` holds 390 backend tests, including
one per validator condition and one per self-check. The frontend holds 241 clip
brief tests: 146 pure-logic tests and 95 component source-contract tests.
