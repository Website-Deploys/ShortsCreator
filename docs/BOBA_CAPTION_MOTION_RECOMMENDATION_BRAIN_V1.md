# BOBA Caption + Motion Recommendation Brain V1

## Purpose

BOBA Caption + Motion Recommendation Brain V1 turns saved BOBA clip intelligence
into compact, deterministic caption and motion advice for selected and backup clip
briefs. It is a local advisory layer between editorial reasoning and a future
human-approved editing handoff.

V1 does not edit, render, download, or inspect media. It does not change Olympus
Editing V2 timelines or Rendering V2 filtergraphs.

## Inputs

The engine requires a saved BOBA Clip Brief Generator V1 artifact and can consume:

- Hook + Retention Brain V1
- Creative Director V2
- Editorial Decision Engine V1
- Clip Ranking Brain V1
- Candidate Clip Discovery V1
- Whole Video Understanding V1
- Explanation Engine V1
- anonymous face/motion validation metadata
- anonymous multi-speaker validation metadata
- analysis signal health
- bounded BOBA project memory

Missing optional inputs lower confidence and activate conservative fallbacks. No
full transcript, raw frame, raw media, face identity, speaker identity, external
API result, or copyrighted asset reference is copied into the artifact.

## Caption Recommendations

Each selected or backup brief receives:

- a bounded caption style
- low, medium, or high density
- calm, normal, fast, or punchy rhythm
- a first-three-second caption instruction
- three-to-eight bounded keyword candidates when evidence supports them
- optional emotional emphasis words
- a payoff caption instruction
- readability notes and explicit avoid guidance

The deterministic style rules prefer:

- `keyword_highlight` or `educational_steps` for educational clips
- `emotional_emphasis` or `clean_subtitles` for emotional clips
- `bold_hook_captions` or `punchline_caption` for high-energy clips
- `minimal` when caption overload is flagged
- `no_captions` when a transcript cannot be verified

Keyword candidates come only from bounded saved titles, angles, instructions,
topics, hook directions, and explanation evidence. They are not a transcript
reconstruction.

## Motion Recommendations

Each recommendation includes:

- motion style and intensity
- zoom moments
- punch-in moments
- stable moments
- layout-safe moments
- visual emphasis moments
- payoff emphasis guidance
- explicit avoid guidance

Strong hooks and payoffs can receive one controlled punch-in or zoom when supplied
safety metadata supports it. Emotional or calm clips prefer subtle motion.
Educational clips prefer stable or subtle motion.

Missing face or layout truth prefers `stable`. Face cutoff or multi-speaker layout
risk prefers `layout_safe`. V1 never identifies a face or speaker and never
invents an active-speaker association.

## Timing Map

Timing is clip-relative and advisory:

- `seconds_0_to_3` supports the saved hook
- `seconds_3_to_10` establishes context with reduced styling
- `middle_section` preserves clarity and retention
- `payoff_section` supports the complete payoff
- `ending_section` stops unnecessary motion and preserves the ending

Typed caption and motion timestamps include a start, end, action, reason, and
priority. They are not executable Olympus timeline events.

## Safety Review

The safety review reports:

- face cutoff risk
- multi-speaker layout risk
- unavailable face or layout signals
- caption overload and readability risk
- over-motion or under-motion risk
- hook distraction risk
- blockers, warnings, and conservative fixes

Anonymous render-validation metadata may be summarized from existing render
manifests. The BOBA artifact stores no bounding boxes, raw frames, identities, or
biometric profiles.

## Recommendation Scores

Every clip receives bounded 0–100 scores for:

- caption fit
- caption readability
- motion fit
- motion safety
- hook support
- retention support
- overall recommendation

These scores compare local saved metadata. They are not audience predictions,
watch-time measurements, virality claims, or proof that an effect rendered.

## Clip-Brief Enhancements

The artifact proposes improved caption and motion instructions, keyword
highlights, zoom notes, punch-in notes, and layout/readability warnings.
`apply_suggestion` is always `false` in V1. The source Clip Brief artifact is not
mutated.

## Artifact

The BOBA store writes atomically to:

```text
work/boba/projects/<project_id>/caption_motion/index.json
```

Schema version:

```text
boba_caption_motion_recommendation_brain_v1
```

Old projects remain loadable. A missing artifact returns a clear unavailable
response rather than fabricated recommendations.

## API

Generate from saved local BOBA artifacts:

```text
POST /api/v1/boba/projects/{project_id}/caption-motion
```

Read the saved artifact:

```text
GET /api/v1/boba/projects/{project_id}/caption-motion
```

Neither route downloads media, calls external APIs, or starts rendering.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_caption_motion.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_caption_motion.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_caption_motion.py --project-id PROJECT_ID
```

Synthetic validation covers educational, emotional, high-energy, layout-risk,
and weak-hook clips. Reports are written under the ignored directory:

```text
work/validation_reports/boba_caption_motion/
```

## Limitations

- V1 is advisory and does not automatically alter captions or motion.
- V1 does not render clips or prove that recommendations are visible in an MP4.
- V1 does not inspect raw media or validate exact transcript wording.
- V1 does not identify faces, people, or speakers.
- V1 does not select music or make copyright-safety claims.
- V1 does not call external APIs or predict real viewer behavior.
- Human review remains required for source fidelity, readability, framing,
  motion safety, rights, and final rendered output.
