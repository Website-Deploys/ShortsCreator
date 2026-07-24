# BOBA Music Mood Brain V1

## Purpose

BOBA Music Mood Brain V1 turns saved BOBA clip intelligence into bounded,
human-reviewable audio guidance for selected and backup clips. It is a local,
deterministic advisory stage. It does not alter Olympus editing or rendering.

## What It Produces

For each selected or backup clip brief, the brain produces:

- a primary and secondary mood;
- an energy level, emotional direction, pacing fit, and music role;
- a clip-relative audio energy map for the hook, context, middle, payoff, and ending;
- speech-priority, ducking, music-level, SFX-level, and silence guidance;
- a conservative SFX recommendation;
- an audio risk review;
- bounded mood, clarity, SFX, emotion, retention, and overall fit scores;
- a suggested clip-brief enhancement with `apply_suggestion=false`.

Blocked briefs are not processed. Original clip briefs are not mutated.

## Inputs

The required input is a saved BOBA Clip Brief Generator V1 artifact. The brain
can also consume:

- Hook + Retention Brain V1;
- Caption + Motion Recommendation Brain V1;
- Creative Director V2;
- Editorial Decision Engine V1;
- Clip Ranking Brain V1;
- Candidate Clip Discovery V1;
- Whole Video Understanding V1;
- Explanation Engine V1;
- local audio-energy and silence signal metadata;
- bounded BOBA memory;
- non-identifying local music-manifest availability metadata.

Missing optional inputs lower confidence and activate conservative fallback
guidance. No missing signal is fabricated.

## Mood Selection

V1 maps supplied clip evidence to a bounded vocabulary:

- motivational material: motivational, inspiring, or heroic;
- emotional material: emotional, cinematic, or minimal;
- educational material: educational clean, minimal, or calm;
- tense material: tense, suspenseful, or mysterious;
- funny material: funny or upbeat;
- luxury/status material: luxury or cinematic;
- serious speech-heavy material: minimal or educational clean;
- weak evidence: minimal or no music, with a warning.

The output is a mood recommendation only. It contains no music name, asset
identifier, URL, or file path.

## Audio Energy Map

Each recommendation describes intended energy for:

1. seconds 0-3;
2. seconds 3-10;
3. the middle section;
4. the payoff section;
5. the ending section.

Local RMS energy metadata can make this advice more conservative. Local silence
events are converted to clip-relative protected-pause notes. These notes do not
change clip boundaries or create an executable edit timeline.

## Speech Clarity And Ducking

Speech remains primary. Educational and speech-heavy clips receive critical
speech priority; emotional, tense, cinematic, and serious clips receive high
priority. Every recommendation includes speech-led ducking guidance.

If music is later approved, downstream mixing should lower it during spoken
phrases and restore it only in verified gaps. V1 does not configure or run a
mixer, and it does not claim that clarity passed a rendered-output check.

## SFX Recommendation

SFX guidance is deliberately conservative:

- emotional, educational, and serious speech generally use none or light SFX;
- a supported high-energy hook may use light or moderate SFX;
- one clean hook or payoff accent is preferred over repeated hits;
- SFX should never mask meaningful speech or fill an emotional pause;
- noise-like SFX are explicitly discouraged.

Olympus remains responsible for resolving safe local SFX and reporting what was
actually mixed.

## Audio Risk Review

Each clip flags:

- music overpowering risk;
- wrong-mood risk;
- speech-clarity risk;
- SFX-overload risk;
- silence-damage risk;
- emotional-mismatch risk;
- mandatory rights review for any external music.

Risk warnings are advisory and do not establish ownership, permission, or
copyright safety.

## Scores

All component scores and the overall audio score are clamped to `0-100`. They
measure recommendation fit against supplied metadata. They are not predictions
of audience behavior, virality, watch time, or commercial performance.

## Persistence

The BOBA store writes atomically to:

```text
work/boba/projects/<project_id>/music_mood/index.json
```

The artifact is small JSON and excludes raw media, full transcripts, voice
identity, music names, URLs, and file paths.

## API

Generate recommendations from saved BOBA artifacts:

```text
POST /api/v1/boba/projects/{project_id}/music-mood
```

Read the saved artifact:

```text
GET /api/v1/boba/projects/{project_id}/music-mood
```

The POST route does not render, download, call an external API, or select music.

## Validator

Run the local checks:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_music_mood.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_music_mood.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_music_mood.py --project-id PROJECT_ID
```

Reports are written under ignored
`work/validation_reports/boba_music_mood/`.

## Limitations

- V1 is advisory and defaults every brief enhancement to not applied.
- It does not render, mix, or modify media.
- It does not download music or call external services.
- It does not name or select music.
- It does not override Olympus editing or rendering.
- Manifest awareness reports availability only and does not prove usage rights.
- Local energy/silence metadata does not replace human listening.
- It does not prove viewer performance or replace editorial and rights review.
