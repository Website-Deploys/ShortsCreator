# BOBA Hook + Retention Brain V1

## Purpose

BOBA Hook + Retention Brain V1 evaluates the opening and retention guidance for
each **selected** BOBA clip brief. It turns existing local BOBA evidence into a
bounded, explainable advisory artifact without modifying the brief or triggering
Olympus editing or rendering.

V1 helps reviewers answer:

- Is the first-three-second direction clear and immediate?
- Does the opening create a supported curiosity or value gap?
- Where could context, filler, pacing, captions, motion, or audio cause drop-off?
- Is the saved payoff complete and timed clearly?
- Which best, safest, and boldest hook directions deserve human review?

## Inputs

The only required input is the saved BOBA Clip Brief Generator V1 artifact.
When available, the engine also consumes:

- Creative Director V2 clip direction
- Editorial Decision Engine decisions and risk review
- Clip Ranking score breakdown
- Candidate Discovery context and payoff flags
- Whole Video Understanding section signals
- Explanation Engine evidence availability
- Olympus virality summary scores
- bounded BOBA project-memory warnings

Missing optional artifacts lower confidence and are recorded in `signal_usage`;
they do not cause BOBA to invent evidence.

## Hook Analysis

For each selected clip, V1 records:

- normalized hook type
- bounded hook strength and first-three-second clarity scores
- current curiosity-gap and pattern-interrupt direction
- opening-line and visual-opening direction
- detected hook risk
- a stronger advisory direction
- an explanation of the local signals used

Scoring combines available BOBA ranking, creative-quality, and virality scores
with deterministic metadata cues. Every score is clamped to `0–100`. Scores are
comparative editorial guidance—not watch-time measurements, audience
predictions, or guarantees of virality.

## Hook Alternatives

Each analysis contains three to five alternatives:

- `best`: balanced recommendation that preserves the saved angle
- `safest`: direct-value wording closest to verified saved evidence
- `boldest`: a supported contrast/tension direction requiring human verification
- `backup`: educational open-loop fallback
- `avoid`: an explicit example of vague, unsupported, or over-edited treatment

Alternatives reuse the saved clip angle and instructions. They do not invent
transcript facts, unsupported superlatives, or new claims.

## Opening And Retention Plan

The plan separates:

1. `seconds_0_to_3`: immediate hook and curiosity/value promise
2. `seconds_3_to_10`: minimum context while preserving forward motion
3. `middle_hold_strategy`: new information, tension, and filler control
4. `payoff_timing_strategy`: complete supported payoff and protected ending
5. `ending_replay_trigger`: final punch or visual echo without a fabricated claim

Pacing notes and retention tactics preserve compatible Creative Director V2 and
Clip Brief guidance.

## Drop-Off Risk Review

V1 reports:

- slow start
- unclear context
- weak payoff
- filler
- over-editing
- under-editing
- caption overload
- audio distraction

Each active risk can produce a bounded fix, blocker, or warning. Detection is
based only on saved metadata; it is not a real audience-retention curve.

## Clip-Brief Enhancements

`brief_enhancements` proposes:

- a stronger opening-line direction
- a restrained pattern interrupt
- a clearer first caption
- safer payoff timing
- an ending/replay trigger
- a retention warning

`apply_suggestion` is always `false` in V1. The original clip brief is not
mutated, and Olympus editing/rendering is not invoked.

## Persistence

The artifact is atomically stored at:

```text
work/boba/projects/<project_id>/hook_retention/index.json
```

Schema version:

```text
boba_hook_retention_brain_v1
```

The artifact is small JSON. It stores no raw media, full transcript, selected
music asset, secret, or external-service payload.

## API

Generate from saved local BOBA artifacts:

```text
POST /api/v1/boba/projects/{project_id}/hook-retention
```

Read the saved artifact:

```text
GET /api/v1/boba/projects/{project_id}/hook-retention
```

The GET route returns a clear not-found response when no artifact exists. Neither
route downloads media, calls an external API, edits a timeline, or renders.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_hook_retention.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_hook_retention.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_hook_retention.py --project-id PROJECT_ID
```

Synthetic mode includes strong-hook, weak-hook, missing-payoff, strong-payoff,
and slow-start cases. Reports are written under
`work/validation_reports/boba_hook_retention/` and remain ignored.

## Limitations

- V1 is advisory and does not render or prove that an effect was applied.
- V1 does not measure real viewers, watch time, retention curves, or replay.
- V1 does not guarantee virality, growth, engagement, or production readiness.
- V1 does not call external APIs or use internet trend research directly.
- V1 does not establish rights or copyright safety.
- V1 cannot repair missing source evidence and never fabricates it.
- A human must verify opening accuracy, context, payoff, pacing, captions, audio,
  rights, and the final rendered result.
