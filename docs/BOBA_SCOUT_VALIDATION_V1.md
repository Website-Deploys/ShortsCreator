# BOBA Scout Validation V1

## 1. Scope and verdict

A validation record for Content Scout V2, covering roadmap item #45. The
component document `docs/BOBA_CONTENT_SCOUT_V2.md` is unchanged and remains the
description of what Scout does.

The audit verdict was **Outcome B: the production logic is correct, and the
validation proof was incomplete.** No production defect was found, **no
production change was necessary, and none was made.** `src/olympus/boba/content_scout.py`
ends this work byte-identical to baseline `main @ a5ff4e4`, sha256
`3be96ab1c83402068ab17b103680ba78df9c2f6a0c3599f1004262206bb03241`.

What changed is proof, in three artifacts:

- **`tests/unit/test_boba_content_scout_v2.py` — 76 tests, all passing.**
  `test_01`–`test_47` are the 47 pre-existing tests, byte-identical to baseline;
  `test_48`–`test_75` are 28 new behavioural tests; `test_helper_matchers_are_falsifiable`
  is a single helper-falsifiability test that proves the negation-aware string
  matchers used by `test_56` and `test_68` actually fire rather than passing
  because they match nothing.
- **`tools/validate_boba_content_scout_v2.py` — 26 named scenarios,** extended
  in place. `--synthetic-project` executes **26, passes 26**, with
  `scenarios_not_applicable` empty, no errors, and exit 0. `--self-check` exits
  0. `--project-id` against an absent project exits 1 through the honest-absence
  path with no traceback, recording only `26_missing_artifact_not_fabricated`
  and listing the other 25 as not evaluated.
- **This document.**

Two figures in the design were corrected by measurement, and both corrections
are recorded here rather than quietly adopted: the rounding-sensitive value
count (section 5) and the claim that a `duplicate_of` field exists on the
recommendation contract (section 6).

## 2. Ownership map

Content Scout V2 owns three things and nothing else.

| Concern | Owner | Status after this work |
|---|---|---|
| Metadata-only candidate scoring | `content_scout.py` (`BobaContentScoutV2`) | unchanged |
| Advisory recommendations | `content_scout.py` `_recommend` | unchanged |
| Review-queue ordering | `content_scout.py` `_queue` | unchanged |
| Rights clearance | Rights and Permission Gate | unchanged, not consulted by Scout |
| Editorial selection | `editorial_decision.py` | unchanged |
| Render authorization | `editorial_decision.py` (`render_readiness`) | unchanged |
| Candidate discovery / ingestion | `clip_discovery.py` | unchanged |

Scout does not clear rights, does not select clips, does not authorize a render,
and does not ingest media. The Rights and Permission Gate, Editorial Decision,
and Clip Discovery remain the unchanged owners of their concerns; this work
touched none of them, and added no parallel scoring or selection authority.

## 3. Authority boundaries

**Recommendation is not approval.** A recommendation is one of `review_now`,
`save_for_later`, `seek_permission`, `blocked`, `reject`, and states what a
human might consider next. `test_64` asserts that every emitted value belongs to
that set of five, so no sixth value expressing approval can appear unnoticed.

**Queue placement is not authorization.** Recommendations are reachable only
through the five `review_queue` lists — `top_items`, `backup_items`,
`permission_needed_items`, `blocked_items`, `duplicate_or_similar_items`. No
list means "approved". `test_62` pins the top-level field set to exactly the
thirteen documented names — `created_at`, `imported_sources`, `limitations`,
`project_id`, `rejected_items`, `review_queue`, `schema_version`,
`scored_items`, `scout_items`, `scout_summary`, `signal_usage`, `source_id`,
`warnings` — which is also how the **absence of a top-level `recommendations`
field** is proven: a field set asserted by equality cannot gain one.

**`human_review_required` is an unconditional constant.** It is hardcoded `True`
at `content_scout.py:1131` and had **zero assertions** at baseline. `test_65`
asserts it on every recommendation across all five queue lists and across all
six rights statuses; `test_66` asserts it stays `True` where
`rights_review_required` is `False`, establishing that the two flags are
independent. The constant stays a constant: nothing here asks for it to become
computed.

**`published_at` is source metadata, and the exact-key-match trap protects it.**
`published_at` records when the *source video* was published. It asserts
nothing about approval. `test_61` scans the serialized Scout_Set for
authority-bearing field names — `approved`, `authorized`, `selected`,
`render_ready`, `publish` — using **exact key matching at every depth**. A
substring or prefix scan for `publish` would match `published_at` and produce a
false failure, and the obvious "fix" for that false failure is to delete a
legitimate metadata field. `test_63` asserts the field is retained on the scout
item and absent from every recommendation. The related timestamp-regex version
of the same trap is in section 8.

## 4. Metadata-only boundary

Content Scout V2 reads local and user-supplied metadata exclusively: no
scraping, no URL fetching, no media download, no external API call, and no
inspection of media bytes. `test_70` asserts that a supplied `source_url` is
retained without any fetch attempt and that the review questions instruct a
human to open a reference manually only if authorized.

The **authoritative** proof is `test_43`–`test_46`, retained byte-identical.
They monkeypatch `subprocess.run`, `Path.write_bytes`,
`urllib.request.urlopen`, and `socket.create_connection` to raise, then execute
real Scout behaviour. Primitive-blocking beats flag-reading for one reason: a
blocked primitive fails when the behaviour occurs, whereas a self-reported flag
such as `signal_usage.external_api_used` is the engine describing its own
behaviour and would keep reading `False` even if the behaviour changed. This is
why the three surviving flag-derived report fields are excluded from every
`passed` calculation (sections 7 and 10) rather than being treated as evidence.

Import refusals are asserted from real output as well: `test_71` (the 2,000,000-byte
import ceiling) and `test_72` (`_safe_local_path` refusing a non-local path)
both assert that a `ValidationError` is raised **and** that its message
identifies the cause.

## 5. The G2 vacuity finding

The audit recorded G2 — removal of the score clamp — as undetected, and
diagnosed it as a fixture-strength gap. Measurement, taken twice
independently, superseded that diagnosis: the unreachability is **structural,
not fixture-specific**. R1.8 requires this section to exist so the finding is
not re-litigated.

`_clamp` at `content_scout.py:127-129` is `round(max(0.0, min(1.0, value)), 4)`
— three limbs. Every additive `_score` component caps its terms with `min(...)`,
and the summed ceilings are:

| Component | Ceiling |
|---|---|
| `creator_fit_score` | 0.75 |
| `topic_fit_score` | 0.76 |
| `shortability_score` | 0.82 |
| `hook_potential_score` | **0.91 (global maximum)** |
| `emotional_story_score` | 0.80 |
| `trend_context_score` | 0.53 |
| `novelty_score` | 0.80 |
| `review_priority_score` | 0.8095 (convex combination, weights sum to 1.00) |
| `confidence` | 0.85 |

No metadata input can drive a clamped value above `0.91`. The three values
observed at exactly `1.0` are `rights_readiness_score`, a direct dictionary
lookup at `content_scout.py:975-982` that **bypasses `_clamp` entirely**. The
only subtracting clamp site, `_clamp(score.confidence - 0.08 - index * 0.04)` at
`content_scout.py:1184`, has a floor of `0.14`. And `BobaScoutScoreV2` declares
`ge=0.0, le=1.0` on all ten score fields at `content_scout.py:241-250`, a
**second independent guard** behind the clamp.

The reachable, load-bearing limb is therefore `round(value, 4)`.

### Fixture strengthening — measured

Two candidates were added to `build_synthetic_scout_items()`, additively; no
existing candidate was mutated or retuned.

- `hook_saturated_owned` — saturates the hook component to its structural
  ceiling.
- `blocked_emotional_duplicate` — simultaneously `blocked` and a duplicate,
  which is the only way to reach the blocked-before-duplicate branch-order
  property (section 6).

| Measurement | Baseline | After strengthening |
|---|---|---|
| Score values on `scored_items` | 80 | **100** |
| Rounding-sensitive values (would change if `round(v, 4)` were removed) | 26 | **32** |
| Values outside `[0.0, 1.0]` with `_clamp` replaced by identity | 0 of 80 | **0 of 100** |
| Angle `confidence` values | — | 17, of which **8** rounding-sensitive |

**The design predicted 31 rounding-sensitive values. The measured figure is 32.**
This is recorded as a measurement correcting a prediction. R1.1 asks only that
the count rise above the measured 26, which 32 satisfies, and the fixture was
**not** retuned to force the predicted number — retuning a fixture to match a
prediction is exactly the practice this validation exists to prevent.

`hook_saturated_owned` measured `hook_potential_score = 0.91`, the fixture
maximum and equal to the structural ceiling, and `review_priority_score = 0.7955`.
An earlier design figure of `0.7847` for that value was **corrected to the
measured 0.7955**; `test_51` asserts the measured values.

The identity-clamp measurement confirms both halves of the finding at once: **0**
of the 100 values fell outside `[0.0, 1.0]` — the bound limbs are structurally
unreachable — while **32** lost their four-decimal form. Bound enforcement is
retained only as a labelled tripwire (`test_48`), explicitly marked in the test
as an assertion no available input can falsify, and `scores_bounded` is excluded
from the validator's `passed` formula because a term guaranteed by the contract
layer is a term R9.11 forbids.

Recommendation distribution over the strengthened 10-candidate fixture:

| Recommendation | Count |
|---|---|
| `review_now` | 4 |
| `seek_permission` | 2 |
| `blocked` | 2 |
| `save_for_later` | 1 |
| `reject` | 1 |

Requirement 1's **original** formulation — that fixture metadata drive a
pre-clamp score above `1.0` — was unsatisfiable without changing engine
coefficients, which Requirement 13 and the Non-Goals forbid. `requirements.md`
Requirement 1 was amended during the design phase onto the reachable
four-decimal rounding limb, so requirements and design agree. This is settled,
not open.

## 6. The G5 proxy finding

The audit recorded G5 — removal of the duplicate branch — as undetected, even
though `test_22_duplicate_item_lowers_novelty` existed. The reason is that
`test_22` asserts two outcomes with an **independent cause**: novelty reduction
happens in `_score` (`:974`) and `duplicate_or_similar_items` membership happens
in `_queue` (`:1214`), both driven by `duplicate_of`. Neither is produced by the
`_recommend` branch, so neither is proof of the duplicate-to-reject decision.
At baseline the string `"reject"` appeared **zero times** in the test file while
the engine did emit it. `test_52` now asserts `recommendation == "reject"` read
from the real `review_queue`, together with the duplicate's `duplicate_of`
identifying the earlier candidate, so the asserted recommendation demonstrably
belongs to the duplicate rather than to the original.

**A design claim was false and is corrected here: there is no `duplicate_of`
field on the recommendation contract.** `duplicate_of` lives on the scout item /
score surface, not on the recommendation. The branch-coupled evidence on a
recommendation is therefore `recommendation.reason`, not a recommendation-level
`duplicate_of`, and not `score.warnings`.

That correction is what makes the branch-order proof work. The measured
behaviour of `blocked_emotional_duplicate`:

- `recommendation == 'blocked'`;
- `reason` exactly `'The user-provided rights status is blocked.'`;
- present in **both** `blocked_items` **and** `duplicate_or_similar_items`.

Dual membership on its own proves only that the candidate is both things. Dual
membership **plus** the blocked reason is what proves the blocked check runs
ahead of the duplicate check, because the reason string is emitted by the branch
that won. `test_54` and scenario `04_blocked_precedes_duplicate` assert exactly
that pairing.

## 7. The nine tautologies and the `privacy` block vector

Nine conjuncts in the validator's `passed` formula had outcomes fixed
independently of engine behaviour. All nine were **removed from `passed`**.

| # | Conjunct | Site | Why it was a tautology | Disposition |
|---|---|---|---|---|
| 1 | `rendering_triggered` | declared `:60-65`, read `not report.X` at `:451-456` | defaults `False`, zero assignment sites | **field deleted** |
| 2 | `downloading_triggered` | same | defaults `False`, zero assignment sites | **field deleted** |
| 3 | `url_fetching_triggered` | same | defaults `False`, zero assignment sites | **field deleted** |
| 4 | `external_calls_made` | same | defaults `False`, zero assignment sites | **field deleted** |
| 5 | `media_required` | same | defaults `False`, zero assignment sites | **field deleted** |
| 6 | `secrets_required` | same | defaults `False`, zero assignment sites | **field deleted** |
| 7 | `external_api_used_false` | reads a `Literal[False]` contract field | the type system fixes the result | retained, **non-gating** |
| 8 | `url_fetching_used_false` | reads a `Literal[False]` contract field | the type system fixes the result | retained, **non-gating** |
| 9 | `downloading_used_false` | reads a `Literal[False]` contract field | the type system fixes the result | retained, **non-gating** |

The first six had **zero assignment sites and zero legitimate consumers**, so
they were deleted outright rather than replaced. Deletion beats replacement
here: `test_43`–`test_46` already prove the same properties by blocking
primitives, and inventing a scenario to re-derive them would add a weaker
statement of an already-proven fact (R9.9, R10.3).

Fields 7–9 could not be deleted, because the protected `test_41` consumes them.
They are retained purely for backward compatibility, are **excluded from every
`passed` calculation**, and are **not evidence of behaviour** (section 10).

`scores_bounded` was likewise dropped from `passed` while retained as a recorded
observation, since `BobaScoutScoreV2`'s `ge`/`le` constraints already guarantee
it (section 5).

### The tenth vector, deliberately not used

The store export self-reports a `privacy` block — **10 hardcoded `True`/`False`
literals** emitted by `export_content_scout_v2` (`store.py:1061`). It is a
readily available, comfortable-looking source of green checkmarks, and it is a
tautology of exactly the same shape as the nine above. It was **deliberately not
used as evidence.** `test_74` derives the export-exclusion assertions from the
**absence of the excluded keys in the exported payload** — `source_path` on
`imported_sources`, and `source_url`, `permission_notes`, `user_notes`,
`raw_metadata_summary` on `scout_items` — plus empty `suggested_review_questions`
on every recommendation across all five queue lists.

## 8. The two timestamp locations

Scout has **exactly two** nondeterministic locations: root `created_at`
(`content_scout.py:347`) and every `imported_sources[].imported_at`
(`content_scout.py:202`).

Roadmap #44's single-timestamp exclusion rule does **not** transfer. Applied
here it would leave `imported_at` inside the compared surface and produce a
false determinism failure on every run — a failure whose most tempting "fix" is
to loosen the comparison further.

A recursive strip-all-`created_at` is **forbidden**. The exclusion set is
constructed positionally from the two documented locations, and `test_57`
additionally asserts that the set of all `created_at` / `imported_at` paths
equals exactly that set — so a *third* nondeterministic timestamp introduced
later fails loudly instead of being silently swallowed by a recursive rule.
`test_57` also identifies the differing field path on failure, and `test_58`
plus scenario `12_queue_order_stable` cover ordering of `scout_items`,
`scored_items`, and each of the five queue lists.

`published_at` must stay **inside** the compared surface, and this is where a
key-name heuristic fails. Measured on the real payload: **10 `published_at`
paths exist**, all of them legitimate source metadata. A timestamp-shaped key
regex such as `.*_at$` would wrongly capture **8 of them**, excluding real
source metadata from the determinism comparison and opening a channel through
which genuine nondeterminism could hide. No heuristic is used.

## 9. Negative-control results

All eight mutations were applied **one at a time** to
`src/olympus/boba/content_scout.py`, AST-validated, measured, then reverted with
`git checkout --`. After every single control the file's sha256 was re-verified
as `3be96ab1c83402068ab17b103680ba78df9c2f6a0c3599f1004262206bb03241`, identical
to baseline `main @ a5ff4e4`.

**8 of 8 detected.** In every case `--synthetic-project` exited 1 with **zero
validator errors and zero silently-skipped scenarios**. The table is transcribed
from the actual runs.

| Control | Requirement | Guard site | Mutation | Validator scenarios FAILED | Tests failed |
|---|---|---|---|---|---|
| G1 | R1.6 | `_clamp` :127-129 | drop `round(..., 4)`, keep bounds | `01_scores_rounded_to_four_decimals`, `02_angle_confidence_rounded_to_four_decimals` | 3: `test_42`, `test_49`, `test_50` |
| G2 | R2.6 | `_recommend` :1064 | neutralise the `elif duplicate_of:` branch | `03_duplicate_recommends_reject` | 3: `test_42`, `test_52`, `test_65` |
| G3 | R3.8 | `_normalized_rights` :370-375 | return `unknown` with no warning | `05_unsupported_rights_normalizes_to_unknown` | 3: `test_15`, `test_42`, `test_53` |
| G4 | R1.6 | `_clamp` call :1184 | drop rounding on angle confidence | `02_angle_confidence_rounded_to_four_decimals` | 2: `test_42`, `test_50` |
| G5 | R2.6, R3.8 | `_duplicate_map` :667 | return an empty duplicate map | `03_duplicate_recommends_reject`, `04_blocked_precedes_duplicate`, `12_queue_order_stable` | 6: `test_22`, `test_30`, `test_42`, `test_52`, `test_54`, `test_65` |
| X1 | R5.6 | `manual_items` ingest :715 | mutate caller-supplied rows in place | `13_upstream_inputs_unmutated` | 2: `test_42`, `test_59` |
| X2 | R7.6 | `_recommend` :1131 | `human_review_required=False` | `16_human_review_always_required`, `17_human_review_independent_of_rights_review` | 3: `test_42`, `test_65`, `test_66` |
| X3 | R8.7 | limitations :855 | delete one engine-authored limitation string | `18_performance_limitations_present` | 2: `test_42`, `test_67` |

Note for a future reader rerunning G1: **the detector is the four-decimal
assertion, not a bound assertion.** Expecting a bound failure and not seeing one
would lead to the wrong conclusion that the control is broken. See section 5 for
why no bound assertion can fail.

### Two controls were weak evidence before they were strong evidence

On the first sweep, **G3 and G5 did not fail their target scenarios. They made
those scenarios report not-applicable instead.**

The root cause was **circularity in the scenario preconditions**:

- Scenario `05_unsupported_rights_normalizes_to_unknown` selected its subject
  **by the presence of the very warning it then asserted**. Remove the warning
  and there was no subject to assert against.
- Scenarios `03` and `04` took their precondition from `_duplicate_map` — the
  engine helper under test. Return an empty map and there were no duplicate
  pairs to examine.

In both cases, neutralising the guard made the scenario select nothing and skip
silently. Detection still occurred, but only through the synthetic-mode coverage
gate that requires `scenarios_not_applicable` to be empty — a backstop, not the
intended detector.

The preconditions were then **decoupled from the asserted property**. Scenario
`05` now selects by the fixture-authored probe item id regardless of whether any
warning was emitted, and `03`/`04` assert against fixture-designed duplicate
pairs rather than the engine's map. After decoupling, all three scenarios fail
properly, as the table records.

The general lesson, stated plainly: **a scenario whose precondition and asserted
property share a single observable is weak evidence, because a regression makes
the scenario vanish rather than fail.** Silent disappearance reads as green on
any report that does not separately police coverage.

### `--self-check` is not a behavioural detector

`--self-check` returned **exit 0 under all eight mutations.** This is by design:
it is a structural gate over the fixture builders and the report model, and it
runs no behavioural scenarios. It must not be relied on as evidence about engine
behaviour. `--synthetic-project` is the behavioural mode.

## 10. Known limitations

- **Metadata-only scoring is not an audience forecast.** Scores estimate
  metadata fit. The engine says so itself in its `limitations` strings, asserted
  verbatim by `test_67`, and `test_68` asserts that no output string asserts a
  prediction, forecast, or guarantee.
- **Rights statuses are user-supplied assertions and confer no clearance.**
  Scout never verifies a rights status and never clears copyright. `test_55`
  asserts every recommendation carries a copyright-uncertainty warning;
  `test_56` asserts no output string states that rights are cleared, verified,
  or confirmed.
- **V1 output is consumed advisorily through `scout_v1=`.**
  `src/olympus/boba/scout.py` remains and is unchanged; V1 artifacts are inputs,
  never authority.
- **`--self-check` is structural only** and detects no behavioural regression
  (section 9).
- **Three retained report fields are not evidence.**
  `external_api_used_false`, `url_fetching_used_false`, and
  `downloading_used_false` read `Literal[False]`-typed contract fields. They are
  kept purely for backward compatibility because the protected `test_41`
  consumes them; they are **excluded from every `passed` calculation** and are
  **not evidence of behaviour**. The authoritative no-network proof is
  `test_43`–`test_46`, which block `subprocess.run`, `Path.write_bytes`,
  `urllib.request.urlopen`, and `socket.create_connection` before running real
  Scout behaviour.
- **There is no project-isolation guard** (section 11).
- **Four pre-existing constraints are tolerated, not repaired.** All were proven
  pre-existing against clean `main @ a5ff4e4`:
  1. `test_boba_output_quality_reviewer.py::test_target_resolution_rejects_external_symlink`
     fails on this checkout.
  2. Three `no-any-return` mypy findings in
     `src/olympus/api/v1/routes/boba.py`.
  3. Three `I001` ruff findings in unrelated `tools/` files.
  4. Four FFmpeg-dependent skips in `test_boba_tool_recovery.py`.

  Nothing in this work repairs any of them, and nothing in this work is blocked
  by them.

## 11. Project isolation as an architectural fact

`analyze()` reads **no `project_id` from a passed artifact**. It operates on
caller-supplied inputs, and the project a Scout_Set belongs to is the
`project_id` passed positionally to `analyze()`. Persistence keys off the
Scout_Set's own `project_id`: `save_content_scout_v2` writes to the path derived
from `scout.project_id` (`store.py:1047`), asserted by `test_73` against
`content_scout_v2_path(scout.project_id)`.

**There is no project-isolation guard in Content Scout V2, and none was added.**
A caller that passes another project's artifact into `analyze()` will have that
data scored, because nothing compares artifact ownership against the requested
project.

That cross-project concern is recorded here as a **limitation only**, per
R12.10–R12.12. Adding a guard would be a production engine change, which the
audit verdict and Requirement 13 forbid, and it would be an unreviewed feature
smuggled in under a validation task. If the concern is to be closed, it belongs
in its own specification.

## 12. Coverage map

Every acceptance criterion, mapped to what discharges it. Criteria already
genuinely proven at baseline are named as such and were not duplicated.

### Requirement 1 — the clamp's reachable limb

| Criterion | Discharged by |
|---|---|
| R1.1 | `hook_saturated_owned` + `blocked_emotional_duplicate`; measured 26 → **32** rounding-sensitive values (section 5) |
| R1.2 | `test_49`, scenario `01_scores_rounded_to_four_decimals` |
| R1.3 | `test_50`, scenario `02_angle_confidence_rounded_to_four_decimals` |
| R1.4 | `test_48`, labelled a structural tripwire; `scores_bounded` excluded from `passed` |
| R1.5 | scenario `01_scores_rounded_to_four_decimals` |
| R1.6 | negative controls **G1** and **G4**; restoration verified by sha256 |
| R1.7 | `git diff -- src/` empty; engine sha256 unchanged |
| R1.8 | **section 5**, including the ceiling table and the amendment record |

### Requirement 2 — duplicates recommended for rejection

| Criterion | Discharged by |
|---|---|
| R2.1, R2.2, R2.3 | `test_52` (recommendation `"reject"` read from `review_queue` via `_recommendations`, plus `duplicate_of`) |
| R2.4 | **section 6**; `test_22` retained but explicitly not counted as proof |
| R2.5 | scenario `03_duplicate_recommends_reject` |
| R2.6 | negative control **G2**; also detected by **G5** |

### Requirement 3 — conservative rights handling

| Criterion | Discharged by |
|---|---|
| R3.1 | `test_53`, scenario `05_unsupported_rights_normalizes_to_unknown`; `test_15` already proved the normalization at baseline |
| R3.2 | `test_19` (baseline), scenario `06_permission_needed_seeks_permission` |
| R3.3 | `test_20` (baseline), scenario `07_unknown_rights_seeks_permission` |
| R3.4 | `test_21` (baseline), scenario `08_blocked_rights_queued_blocked` |
| R3.5 | `test_54`, scenario `04_blocked_precedes_duplicate` (section 6) |
| R3.6 | `test_55`, scenario `09_copyright_uncertainty_warned` |
| R3.7 | `test_56`, scenario `10_no_rights_clearance_claimed`, with `test_helper_matchers_are_falsifiable` proving the matcher fires |
| R3.8 | negative controls **G3** and **G5** |

### Requirement 4 — determinism with two timestamp exceptions

| Criterion | Discharged by |
|---|---|
| R4.1, R4.2, R4.3 | `test_57` (equality under the two-location exclusion; differing path reported; exclusion set asserted exact) |
| R4.4, R4.5, R4.6 | `test_58` |
| R4.7 | scenarios `11_determinism_two_timestamp_exceptions`, `12_queue_order_stable` |

### Requirement 5 — caller inputs never mutated

| Criterion | Discharged by |
|---|---|
| R5.1, R5.2 | `test_59` (deep snapshots of all five inputs, nothing excluded) |
| R5.3 | `test_60` |
| R5.4 | `test_59` maps the `memory` key to `boba_memory=` and asserts the signal-consumption flags |
| R5.5 | scenario `13_upstream_inputs_unmutated` |
| R5.6 | negative control **X1** |

### Requirement 6 — advisory authority boundary

| Criterion | Discharged by |
|---|---|
| R6.1 | `test_61`, scenario `14_no_authority_fields_present` (exact key match — section 3) |
| R6.2, R6.3 | `test_62`, scenario `15_top_level_field_set_exact` |
| R6.4, R6.5 | `test_63` |
| R6.6 | `test_64` |
| R6.7 | no contract field was added; `git diff -- src/` empty |

### Requirement 7 — human review always required

| Criterion | Discharged by |
|---|---|
| R7.1, R7.2, R7.3 | `test_65` |
| R7.4 | `test_66` |
| R7.5 | scenarios `16_human_review_always_required`, `17_human_review_independent_of_rights_review` |
| R7.6 | negative control **X2** |
| R7.7 | the constant at `:1131` is unchanged |

### Requirement 8 — no audience-performance claim

| Criterion | Discharged by |
|---|---|
| R8.1, R8.2, R8.3 | `test_67`, scenario `18_performance_limitations_present` |
| R8.4 | `test_68`, scenario `19_no_performance_claim_strings` |
| R8.5 | `test_69`, scenario `20_angle_field_set_exact` |
| R8.6 | `test_50` (bounded angle confidence) |
| R8.7 | negative control **X3** |

### Requirement 9 — named scenarios replace the tautologies

| Criterion | Discharged by |
|---|---|
| R9.1 | the existing validator extended in place; no second validator exists |
| R9.2, R9.3 | 26 named scenarios, each deriving its result from real `analyze()` output |
| R9.4, R9.5, R9.6 | **section 7**: six default-`False` fields deleted; three `Literal[False]` reads made non-gating; no self-reported flag gates `passed` |
| R9.7 | scenario preconditions decoupled from asserted properties (section 9) |
| R9.8 | no scenario is an existence-only, count-only, source-text, or comment check |
| R9.9, R9.10 | **section 7** disposition table |
| R9.11 | `scores_bounded` and the three flag reads removed from `passed` |
| R9.12 | every scenario id and result written under `--report-dir` |

### Requirement 10 — no-network behaviour preserved

| Criterion | Discharged by |
|---|---|
| R10.1, R10.2, R10.3 | `test_43`–`test_46` retained **byte-identical**; no flag read substituted (**section 4**) |
| R10.4 | no scraping, fetching, downloading, external call, rendering, or publishing introduced into engine or validator |
| R10.5 | `test_70` |
| R10.6 | `test_71` |
| R10.7 | `test_72` |

### Requirement 11 — validator CLI modes

| Criterion | Discharged by |
|---|---|
| R11.1 | `--self-check` exits 0 (structural only — section 9) |
| R11.2 | `--synthetic-project`: **26 executed, 26 passed**, `scenarios_not_applicable` empty |
| R11.3, R11.4, R11.5 | `--project-id` runs only satisfied preconditions; not-applicable ids are absent from `scenario_results` and listed under an explicit not-evaluated heading |
| R11.6 | JSON-safe report written under `--report-dir` |
| R11.7 | the four fixture/helper exports retained and consumed by the test suite |
| R11.8 | absent project exits 1 through the honest-absence path with no traceback and no fabricated result; `26_missing_artifact_not_fabricated` is the only recorded scenario |

### Requirement 12 — persistence and ownership

| Criterion | Discharged by |
|---|---|
| R12.1, R12.2 | `test_73`, scenarios `21_store_round_trip`, `22_store_keys_off_scout_project_id` |
| R12.3, R12.4 | `test_74`, scenarios `23_export_omits_private_keys`, `24_export_empties_review_questions` |
| R12.5 | absence-of-key derivation; the `privacy` block deliberately unused (**section 7**) |
| R12.6 | scenario `25_export_json_safe`; `test_37` (baseline) |
| R12.7 | `test_35` (baseline) — reset scope, not duplicated |
| R12.8, R12.9 | `test_75`, scenario `26_missing_artifact_not_fabricated` |
| R12.10, R12.11, R12.12 | **section 11** |

### Requirement 13 — the engine is unchanged

| Criterion | Discharged by |
|---|---|
| R13.1 | engine sha256 `3be96ab1…bb03241`, identical to `main @ a5ff4e4`; `git diff -- src/` empty |
| R13.2 | sha256 re-verified after each of the eight controls (**section 9**) |
| R13.3 | `src/olympus/boba/scout.py` unchanged; `scout_v1=` still consumed |
| R13.4 | the four `/projects/{project_id}/content-scout-v2` routes unchanged; `test_38`–`test_40` pass |
| R13.5 | 76 passing tests, of which `test_01`–`test_47` are the byte-identical pre-existing set |
| R13.6 | **section 10** — four pre-existing constraints tolerated, none repaired |
