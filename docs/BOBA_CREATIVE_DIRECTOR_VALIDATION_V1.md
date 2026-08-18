# BOBA Creative Director Validation V1

## 1. What this document is

A validation record for Creative Director V2. `docs/BOBA_CREATIVE_DIRECTOR_V2.md`
remains the component document.

The headline finding: **the engine was already correct, and not one line of it
was changed.** What was missing was proof. Three guards could be deleted with the
entire suite and the validator still green, and four correct behaviours had no
assertion anywhere. Sections 7 and 8 are the substance of this work.

## 2. Where Creative Director V2 lives

`src/olympus/boba/creative_director.py`, 2,062 lines, containing **both**
`BobaCreativeDirector` (V1 briefs) and `BobaCreativeDirectorV2Engine` (advisory
direction), merged as PR #41. Entry points: `direct(...)` and
`direct_from_signals(...)`. `project_id` is keyword-only on `direct()`.

## 3. Ownership map — the 15 modules as discovered

Creative Director V2 owns none of the authority it consumes.

| Module | Lines | Owns |
|---|---|---|
| `creative_director.py` | 2,062 | V1 briefs + V2 advisory direction |
| `editorial_decision.py` | 1,426 | clip **selection** and **`render_readiness`** |
| `editorial_policy.py` | 131 | editorial policy thresholds |
| `clip_ranking.py` | 1,266 | ranking scores and tiers |
| `ranking.py` | 214 | ranking support types |
| `clip_discovery.py` | 1,565 | candidate discovery |
| `whole_video.py` | 1,782 | whole-video understanding |
| `explanation.py` | 1,367 | explanations |
| `clip_brief.py` | 1,409 | clip briefs |
| `clip_brief_review.py` | 3,722 | brief review |
| `memory.py` | 81 | memory contracts |
| `project_memory.py` | 298 | bounded project memory |
| `reasoning.py` | 171 | reasoning helpers |
| `brain.py` | 289 | brain dispatch |
| `store.py` (persistence surface) | — | `save/load/path` for `creative_direction_v2` |

## 4. Authority boundaries

- **Selection** belongs to `editorial_decision.py`. Creative Director V2 consumes
  `selected` as a fact; only decisions with a truthy `selected` receive
  direction, capped at ten.
- **`render_readiness`** originates upstream and is reproduced verbatim,
  including `blocked`. The engine never upgrades it. When absent or empty it
  falls back conservatively to `needs_revision`, never to `ready_for_render`.
- **Ranking** belongs to `clip_ranking.py`.
- Creative Director V2 produces **advisory direction only**. It grants no
  approval, renders nothing, reads no media, makes no external call, and
  requires no secret.
- An editorial artifact whose `project_id` differs from the requested project is
  **refused**, with both identifiers in the error payload.

## 5. Evidence, inference, and the fallback model

`signal_usage` carries a `*_used` flag per upstream artifact plus
`unavailable_signals`, `fallback_used`, and `warnings`. Declaring a missing input
is what separates honest degradation from fabricated evidence.

With editorial decisions alone, the engine reports exactly six unavailable
signals — `explanations`, `clip_ranking`, `candidate_discovery`,
`whole_video_understanding`, `analysis_signal_health`, `project_memory` — sets
`fallback_used` true, and warns. With all seven supplied, `unavailable_signals`
is empty and `fallback_used` is false. That inversion is what makes the flags
admissible evidence rather than self-reports, and it is why `test_54` and
`test_55` exist as a discriminating pair.

## 6. What was already proven

Regression anchors, unchanged by this work: `test_15` (layout risk selects safer
motion), `test_16` (unavailable face/layout signals create a warning), `test_19`
(audio direction never includes a copyrighted track path), `test_22` (V1
compatibility), `test_23` (missing editorial fails clearly), `test_24` (JSON-safe
persistence with no `transcript_segments`), `test_25` (API routes and frontend
exposure), `test_26`/`test_27` (validator modes), `test_28`/`test_29`/`test_30`
(no rendering, no external calls, no staging).

Honest note: `test_01`–`test_12` are pure serialization round-trips. They are
useful structural coverage and they are **not** behavioural proof.

## 7. The seven gaps and how each is now closed

| Requirement | Behaviour | Tests | Validator scenario | Guard site |
|---|---|---|---|---|
| 1 | selected-only authority | `test_31`–`test_34` | `01`, `02`, `03` | `:670` |
| 2 | `render_readiness` preserved | `test_44`–`test_47` | `04`, `05` | none — missing assertion |
| 3 | project isolation | `test_35`–`test_37` | `06` | `:656` |
| 4 | missing upstream declared | `test_54`, `test_55` | `07`, `08` | `:650` |
| 5 | scores are not predictions | `test_48`–`test_52` | `09` | none — missing assertion |
| 6 | mood-only audio | `test_53` | `10` | none |
| 7 | conservative motion | `test_38`, `test_39` | `11`, `12`, `13` | `:1504`, `:1509` |
| 8 | determinism | `test_40`, `test_41` | `14` | none — missing assertion |
| 9 | no upstream mutation | `test_42`, `test_43` | `15` | none — missing assertion |
| 11 | persistence | `test_56` | `16` | none |
| 12 | validator asserts semantics | `test_57` | all 16 | — |

### Why two guards were invisible

**Selected-only.** `test_20` asserts `all(item.selected for item in
result.clip_directions)`. That looks like selection authority but proves nothing:
`_clip_direction` **hardcodes `selected=True`** at `creative_director.py:1132`,
so the assertion is true by construction even for a rejected clip. `clip.selected`
is therefore **inadmissible** as evidence. Requirement 1 is proven by
candidate-ID equality derived from the input payload.

**Emotional softening.** The fixture already requests `subtle_zoom` for
`strong_emotional`, so the branch at `:1509` was never armed and deleting it
changed nothing. `test_38` arms it with `high_motion` and `dynamic_zoom`.

## 8. Negative-control results

Method: break exactly one site by hand, AST-validate the mutation, run the
focused pytest selection plus the validator in `--self-check`, restore, confirm
green, confirm zero residue. Failures **and** collection errors were counted.

**Before this work the validator detected 0 of 5 guard removals** — it asserted
only existence flags (`*_present`), counts, and self-reported capability
booleans, with no named scenarios.

| # | Target | Site | Tests failing | Validator | Failed scenarios | Result |
|---|---|---|---|---|---|---|
| G1 | selected-only filter | `:670` | 4 | fails | `01`, `02`, `04` | detected |
| G2 | project isolation | `:656` | 1 | fails | `06` | detected |
| G3 | emotional softening | `:1509` | 2 | fails | `12` | detected |
| G4 | conservative fallback | `:1504` | 2 | fails | `11` | detected |
| G5 | editorial required | `:650` | 2 | fails | `07` | detected |
| N6 | determinism (wall-clock stamped into a compared field) | — | 2 | fails | `14` | detected |
| N7 | non-mutation (write back to the caller's model) | — | 1 | **passes** | — | detected by tests only |
| N8 | readiness default → `ready_for_render` | `:1133` | 2 | passes | — | detected by tests only |
| N9 | engine denial `limitations[2]` deleted | `:818` | 1 | fails | `09` | detected |

**9 of 9 detected. 0 undetected.**

### Three of my own experiments were invalid before they were valid

Recorded because the corrections matter more than the results:

- **N6 first attempt** stamped `now_iso()` into `source_id`, which is already a
  keyword argument at `:805`. The duplicate kwarg raised `TypeError` and crashed
  the validator, which *looked* like detection. Redone by stamping a compared
  field instead.
- **N7 first attempt** wrote a key into the dict returned by `_v2_dict`. That
  function **always copies** — `model_dump(mode="json")` for models, `dict(value)`
  for mappings — so the write never reached the caller and the experiment proved
  nothing. Redone by mutating the caller's model directly, which is the realistic
  defect class.
- **N9 first attempt** used a regex that did not match the real line-split
  string literal, so no mutation was applied at all.

An earlier pass in this repository made the same class of error in the opposite
direction: a shell-quoted replacement inserted a literal `\n`, breaking the file
into a syntax error, and a `^FAILED`-only grep missed the resulting collection
errors. Every sweep here AST-validates the mutation and counts errors as well as
failures.

## 9. The inherited-note correction

`project_direction.human_review_notes[7]` is
`"Scores and tactics do not predict real audience performance."` It is **not
authored by Creative Director V2**. `creative_director.py:1231` splats the
editorial artifact's own `limitations` into `human_review_notes`, so notes 3–8
are verbatim upstream pass-throughs.

A test asserting "the engine emits the audience-performance note at index 7"
would therefore be **testing the fixture, not the engine** — and would keep
passing after both of the engine's own denials were deleted. That is a hollow
test, and it was nearly written into this spec.

What was written instead:

- `test_48` and `test_49` empty the editorial `limitations` **first**, so an
  asserted string cannot have arrived from upstream. They pin the engine's two
  own denials: set-level `limitations[2]` (`:818`) and the
  `hook_treatment.reason_it_should_work` suffix *"This is an evidence-bound
  creative hypothesis, not audience-performance proof."* (`:971`).
- `test_50` proves pass-through separately using an unmistakable sentinel, and
  asserts the sentinel does **not** appear in the engine's own `limitations`.
- **No test asserts a fixed `human_review_notes` index.** Index position is a
  function of how many optional context notes precede it and is not a
  behavioural claim.

Negative control N9 is the direct check: with the engine's denials deleted, the
naive index assertion would still pass, while `test_48` and `test_49` fail.

## 10. `creative_quality_summary` is not a new metric

It is a `BobaCreativeQualityScoreV2` — the same eight craft dimensions
(`hook_quality`, `clarity`, `emotional_pull`, `pacing_strength`,
`visual_direction_strength`, `caption_strength`, `audio_direction_strength`,
`overall_confidence`), arithmetically averaged across clip directions and rounded
to two decimals. `test_52` recomputes that mean from the per-clip scores.

It carries no aggregate health number, does **not** violate the
no-creative-health-score boundary, and must not be "fixed", removed, or replaced.

## 11. Determinism and the `created_at` exception

Two `direct()` calls on identical inputs produce identical output except the
**root** `created_at`, which is documented wall-clock metadata.

The comparison **asserts the root is the only `created_at` path at any depth**
and then removes just that one. It does not strip recursively. All seven upstream
artifacts carry their own `created_at`, and those are canonical evidence — a
blind recursive strip would silently stop comparing an inherited timestamp
exactly where provenance matters. If one is ever echoed into the direction set,
`_canonical` fails loudly and forces a deliberate decision.

Requirement 9's comparison strips **nothing at all**: re-stamping an input would
itself be a mutation.

## 12. Known limitations

- **The validator does not detect two of the nine mutations** (N7, N8). Scenario
  15 passes dict payloads, and `_v2_dict`'s copy makes caller mutation
  structurally impossible on that path, so only the pytest test — which passes
  models — catches a write-back. N8 is likewise covered by tests alone. Both are
  proven by tests; neither is proven by the gate.
- `--project-id` mode executes 11 of 16 scenarios. Scenarios `03`, `08`, `11`,
  `12`, `13` need fixture states a real project may not contain, and fabricating
  them would mean inventing evidence about that project. They are reported in
  `skipped_scenarios`, **absent** from `scenario_results`, never defaulted true.
- The proof is bounded by the synthetic fixture's shape: eight decisions, four
  selected, four readiness values, three framing states.
- No proof is offered about rendering, rights clearance, copyright safety,
  production readiness, or audience performance. This layer validates advisory
  metadata only.
- Requirement 10's advisory boundary rests on the pre-existing anchors
  (`test_28`–`test_30`), which assert a self-reported signal profile rather than
  kernel-level interception. They prove nothing prohibited was *recorded*; they
  are not a sandbox.

## 13. No production engine changes were necessary

**Not one line of `src/olympus/boba/creative_director.py` was changed.** It is
byte-identical to `main @ a9ae621`, verified by SHA-256 comparison after the
sweep.

Every invariant held on unmutated `main`. A production change would have required
a test that is correct under the anti-hollow rules and that fails against
unmutated `main`; no such test emerged. Changing the engine while writing its
proof would have destroyed the proof's value, because the tests would then
describe code written to satisfy them.

## 14. Pre-existing failures, not caused by this work

| Item | Where |
|---|---|
| 1 test failure | `test_boba_output_quality_reviewer.py::test_target_resolution_rejects_external_symlink` — an earlier root-escape guard fires before the expected `external symlink` message |
| 3 mypy `no-any-return` | `src/olympus/api/v1/routes/boba.py:2982,3226,3414` |
| 3 ruff `I001` | `tools/validate_durable_restart_resume.py`, `validate_long_video_full_render.py`, `validate_multi_speaker_layout.py` |
| 4 skips | `test_boba_tool_recovery.py` — FFmpeg/FFprobe absent |

## 15. Out of scope

- No new Creative Director engine; no second validator. `tools/validate_boba_creative_director_v2.py`
  was extended in place, and `tools/validate_boba_scout_creative_director.py`
  remains the untouched V1 validator.
- No second scoring authority, no second clip-selection authority, no numeric
  creative-health score.
- No API route or frontend changes; no V1/V2 redesign; no changes to upstream
  module ownership.
- **The guard-removal sweep is a manual audit methodology. No mutation harness,
  script, marker, or `--mutate` flag exists in this repository**, and none was
  committed.
- No repair of the pre-existing failures in section 14.
