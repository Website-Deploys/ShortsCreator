# Clip Boundary Quality and Story Completeness V2

## Problem

Technically safe trim points can still produce a weak Short when the selected window starts after
the hook, requires missing context, ends before the payoff, drags after the resolution, or repeats
another selected moment. Those are editorial selection problems rather than FFmpeg timing defects.

## Editorial Versus Technical Repair

Editorial boundary quality runs in Planning before Editing. It evaluates whether the requested
source window tells a complete, understandable story and recommends a stronger window.

The existing A/V boundary repair remains authoritative for exact word-safe trim timestamps,
preroll/postroll, synchronized audio/video trims, and caption-relative timing. The flow is:

```text
Planning candidate
-> editorial boundary recommendation
-> A/V word-safe boundary repair
-> rendering
```

## Boundary Quality Scoring

`ClipBoundaryQualityV1` records deterministic scores for:

- hook placement;
- context sufficiency;
- payoff inclusion;
- story completeness;
- pacing density;
- duplicate overlap risk;
- abrupt start and end risk;
- dead-air and post-payoff drag risk;
- evidence confidence.

The engine consumes transcript segments and word timings when available, Story V2 setup/payoff and
context guidance, candidate hook/ending evidence, prior selected ranges, and source duration. Missing
signals produce explicit warnings and conservative fallback scores rather than invented confidence.

## Recommendation Engine

`recommend_clip_boundaries(candidate, context)` can:

- pull a start earlier to recover a nearby hook or required setup;
- trim a short filler/dead introduction;
- extend an ending through a nearby payoff;
- tighten low-value material after a payoff;
- move to transcript boundaries when word timing is unavailable;
- reduce duplicate overlap when a safe alternate start exists;
- clamp the recommendation to configured duration and source limits.

The recommendation never replaces technical A/V repair and never edits media directly.

## Integration

Planning boundary refinement persists `boundary_quality` and `boundary_quality_decision`, then uses
the recommended timestamps for scoring, blueprint generation, and ranking. Editing reads those
recommended timestamps as the requested input to the existing A/V repair contract. Final timelines
retain both the editorial quality metadata and the canonical repaired timeline.

Affected planning/editing stages use new stage versions so stale artifacts do not silently bypass
the recommendation while old projects remain readable through optional metadata fallbacks.

## Metadata

The `boundary_quality` object includes requested and recommended windows, hook/context/payoff timing,
quality component scores, risks, reasons, warnings, confidence, and a deterministic decision record.
The existing `source_window_v1` metadata remains unchanged and separately proves what timestamps the
renderer consumes.

## Validation

Run local synthetic validation:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_clip_boundary_quality.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_clip_boundary_quality.py --simulate
D:\Olympus\.venv\Scripts\python.exe tools\validate_clip_boundary_quality.py --project-id PROJECT_ID
```

Reports are written under `work/validation_reports/clip_boundary_quality/` and remain ignored. The
simulation uses synthetic transcript/story fixtures only; it performs no downloads, network calls,
external API requests, or real-media processing.

## What This Fixes

- explicit editorial boundary quality scoring;
- hook/context/payoff-aware recommendations;
- cleaner payoff endings and less post-payoff drag;
- duplicate overlap risk and warnings;
- honest transcript/story fallback behavior;
- persisted handoff from Planning into existing A/V repair.

## What This Does Not Fix

This pass does not change technical A/V sync drift handling, render checkpoint behavior, BOBA
autonomy, face tracking, music audibility, or release readiness. Synthetic tests do not prove that
every real video will feel human-edited; representative user-approved playback remains necessary.
