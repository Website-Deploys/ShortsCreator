# BOBA Creative Director V2

## Purpose

BOBA Creative Director V2 turns saved BOBA editorial decisions into deterministic, senior-editor-style creative guidance. It describes how selected clips should open, pace, caption, move, sound, retain attention, and deliver their emotional payoff.

V2 is advisory. It does not edit timelines, render clips, download media, call external APIs, select copyrighted songs, or predict audience performance.

## V1 and V2

Creative Director V1 remains available and unchanged. V1 produces compact per-clip briefs at `work/boba/projects/<project_id>/creative_briefs.json` and retains its existing API and approval workflow.

Creative Director V2 adds a separate typed artifact with:

- project-level style and editorial philosophy;
- per-selected-clip opening, hook, pacing, caption, motion, audio, retention, and emotional direction;
- evidence-derived creative quality scores;
- explicit signal usage, fallbacks, warnings, risk fixes, and limitations.

Editorial Decision remains authoritative for selection, render readiness, priority, and baseline treatment. V2 deepens those saved choices; it does not reselect clips or approve rendering.

## Inputs

The only required input is a saved BOBA Editorial Decision artifact. V2 also consumes these saved local artifacts when available:

- Clip Ranking score breakdowns and risk factors;
- Candidate Discovery hook, context, payoff, boundary, and bounded evidence metadata;
- Whole Video Understanding tone, topic, story, emotional, filler, and payoff signals;
- Explanation Engine summaries and bounded reasons;
- analysis signal health, including face/layout, speaker, visual, and transcript availability;
- bounded BOBA Project Memory summaries.

Missing optional inputs produce explicit fallback metadata and warnings. Missing Editorial Decisions fail clearly.

## Project Direction

Project direction contains the overall style, tone, pacing philosophy, caption philosophy, motion philosophy, audio philosophy, target viewer feeling, and human-review notes. It summarizes selected editorial decisions and whole-video context without storing raw media or full transcripts.

## Per-Clip Direction

Each selected clip receives:

- its saved candidate identity, selection state, and render readiness;
- final clip angle and story framing;
- opening three-second plan;
- hook treatment;
- pacing map;
- caption, motion, and audio direction;
- retention plan and emotional arc;
- creative quality score;
- risk fixes, editor notes, warnings, and confidence.

## Opening Three Seconds

The opening plan states what should appear first, what the first caption should imply, which curiosity gap should remain open, which motion choice is safe, and what to avoid. It favors immediate meaning over dead air or slow fades.

## Hook Treatment

Hook direction preserves the Editorial Decision hook strategy and expands it into opening-line direction, first visual emphasis, curiosity trigger, pattern interrupt, evidence-bound rationale, and hook risk. The rationale is a creative hypothesis, not performance proof.

## Caption Direction

Caption direction provides a style, bounded emphasis words, rhythm, highlight moments, readability notes, and warnings. Educational clips favor clean or keyword-highlight captions; emotional clips use more restrained emphasis. V2 does not write or render subtitle files.

## Motion Direction

Motion direction provides zoom, punch-in, stable, layout-safe, and visual-emphasis moments. Missing face or visual-layout evidence forces conservative advisory direction and a visible warning. V2 never claims face tracking or motion was rendered.

## Audio Direction

Audio direction contains only a music mood, SFX intensity, ducking guidance, silence notes, speech-clarity guidance, and warnings. It contains no song title, track selection, asset path, or copyright-safety claim. Speech remains the priority, and heavy SFX receive a caution.

## Retention and Emotion

The retention plan covers the opening hook, curiosity loop, middle hold, payoff delivery, replay trigger, and risks. The emotional arc describes starting, building, and payoff emotions using saved whole-video and candidate evidence when available.

## Creative Quality Score

Scores cover hook quality, clarity, emotional pull, pacing strength, visual direction, captions, audio direction, and overall confidence on a 0–100 scale. They summarize saved evidence and signal availability; they do not predict views, retention, or virality.

## Persistence

The canonical atomic artifact path is:

`work/boba/projects/<project_id>/creative_direction_v2/index.json`

The artifact is JSON-safe, bounded, and versioned as `boba_creative_director_v2`. Old projects without this artifact continue to load normally.

## API

- `POST /api/v1/boba/projects/{project_id}/creative-direction-v2` generates and saves direction from existing BOBA artifacts.
- `GET /api/v1/boba/projects/{project_id}/creative-direction-v2` returns the saved artifact or a clear unavailable response.

Neither route downloads nor renders media.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_creative_director_v2.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_creative_director_v2.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_creative_director_v2.py --project-id PROJECT_ID
```

Reports are written under `work/validation_reports/boba_creative_director_v2/` and must remain untracked.

## Limitations

- Direction remains advisory and does not override Olympus editing or rendering.
- No real media is inspected by the engine or synthetic validator.
- Music is mood metadata only; copyright safety is not established.
- Missing visual, face, speaker, transcript, or upstream BOBA artifacts reduce confidence.
- Human review remains required for meaning, rights, framing, speech clarity, and final edit quality.
