# Creator Personalization V2

Creator Personalization V2 is a local, explicit, user-controlled preference layer for Olympus. It influences existing V2 decisions without replacing Story, Virality, Planning, Editing, Rendering, or safety checks.

## What It Does

- Stores multiple local creator profiles and editable presets.
- Records feedback only when the user explicitly submits it.
- Applies bounded preferences to Planning, Editing, Captions, Music, Motion, and Upload Metadata.
- Persists an honest `personalization_applied_v2` record and a compact `unified_clip_intelligence.personalization` summary.
- Shows the active profile, applied systems, adjustments, warnings, and feedback controls in rendered clip cards.

## What It Does Not Do

- It does not track views, clicks, watch time, or passive behavior.
- It does not infer protected attributes or create personality labels.
- It does not collect credentials, cookies, tokens, private documents, long transcripts, scripts, or lyrics.
- It does not train a model, require login, call a paid API, or sync profiles to a cloud service.
- It does not override copyright, licensing, face/layout, readability, motion, or render safety checks.

## Privacy And Storage

Profiles and feedback are stored as validated JSON under `work/personalization/` by default:

```text
work/personalization/
  active_profile.json
  profiles/
  feedback/
  exports/
  backups/
```

Writes use a temporary file followed by atomic replacement. Existing profiles are backed up before updates. Payload validation rejects credential-like keys/text and long preference text. Feedback notes are limited to 500 characters by default.

The profile privacy contract always records:

- `local_only=true`
- `no_sensitive_data=true`
- `no_cloud_sync=true`
- `exportable=true`
- `resettable=true`

## Presets

| Preset | Intended behavior |
| --- | --- |
| `balanced_default` | Clean, moderate, broadly safe defaults |
| `viral_storyteller` | Curiosity hooks, emotional payoff, stronger captions |
| `clean_podcast` | Measured pacing, minimal SFX/motion, speech-first music |
| `motivational_shorts` | Fast pacing, bold captions, motivational music, controlled motion |
| `music_performance` | Minimal added motion and no intrusive background-music overlay |
| `gaming_reactive` | Faster reaction pacing and higher, still bounded motion |
| `education_clarity` | Clear metadata, simple captions, low distraction |

Presets are starting points. Every stored profile remains editable through the API and frontend.

## Feedback And Learning

The frontend supports Like, Dislike, More like this, Avoid this, category feedback, and an optional short note. The API accepts only controlled ratings, labels, and safe clip traits.

Learning is disabled by default. When the creator explicitly enables it, submitted feedback updates only safe pattern lists and small bounded preferences. Confidence rises gradually and is capped. Viewing a clip never changes a profile.

Safe learned traits include hook category, title pattern, caption style, music mood, motion style, and broad clip traits. Exact transcript or title text is not stored as learned preference data.

## Pipeline Integration

### Planning

Planning receives `personalization_directives_v2` and applies bounded score deltas. Preferences can favor emotional payoff, curiosity hooks, complete stories, conversation moments, and low-context avoidance. Core quality and safety remain primary, and high/blocked-risk clips cannot receive a positive personalization boost.

### Editing

Editing consumes the profile's style preset, pacing, zoom, SFX, caption, music, and motion intensities. A clean podcast profile therefore produces different timeline decisions from a motivational profile. Existing hook, payoff, face tracking, layout, and render safeguards remain active.

### Captions

Caption style, casing, highlight density, and words per line are applied to the exact caption events used for ASS generation. Unknown styles fall back safely, line length stays between two and eight words, and readability/safe-zone validation still decides whether output is acceptable.

### Music

Music preferences can influence mood, instrumental preference, presence, loudness ceiling, and reuse penalty. Presence changes affect the actual music decision or gain. License verification, speech clarity, project disablement, and music-performance protection cannot be overridden.

### Motion

Motion preferences influence style, intensity, zoom density, and avoided effects. Flash remains disabled, shake can be rejected, and unsafe face/layout/caption conditions can limit or disable personalized motion. The manifest reports that limitation instead of claiming motion was rendered.

### Upload Metadata

Upload Metadata V2 ranks already-truthful title candidates with the profile, adjusts description tone, removes banned hashtags, and adds preferred hashtags only when relevant. Existing truth, spam, copied-content, and safety validation runs before personalization. It never introduces claims such as "guaranteed viral" or "copyright safe."

### Unified Truth

Each compatible clip can expose:

```json
{
  "personalization": {
    "applied": true,
    "profile_id": "profile_id",
    "profile_name": "Motivational Shorts",
    "confidence": 0.4,
    "affected_systems": ["planning", "captions", "music"],
    "key_adjustments": [],
    "warnings": []
  }
}
```

`applied=true` means a real downstream decision changed. A planned preference that safety prevented is reported as limited/not applied with a reason.

## API

Local FastAPI routes are available under `/api/v1/personalization`:

- `GET /profiles`
- `POST /profiles`
- `GET /profiles/{profile_id}`
- `PATCH /profiles/{profile_id}`
- `POST /profiles/{profile_id}/activate`
- `POST /profiles/{profile_id}/reset`
- `GET /profiles/{profile_id}/export`
- `POST /profiles/import`
- `POST /feedback`
- `GET /summary`

All payloads are schema validated. Reset and activation are explicit operations; reset clears that profile's feedback.

## Frontend Controls

The results gallery contains a compact profile panel with active-profile selection, preset creation, title/caption/music controls, bounded intensity controls, explicit learning opt-in, export, and reset. Each clip card shows personalization truth and quick feedback controls. Older renders without personalization metadata show `Not available` and continue to load normally.

The UI states: "Personalization is local and based only on your feedback. You can reset this anytime."

## Configuration

Environment variables use the `OLYMPUS_CREATOR_PERSONALIZATION__` prefix. Important defaults include:

- `ENABLED=true`
- `LEARNING_ENABLED_BY_DEFAULT=false`
- `EXPLICIT_FEEDBACK_ONLY=true`
- `STORAGE_DIR=work/personalization`
- `MAX_FEEDBACK_NOTES_CHARS=500`
- `MAX_PROFILES=20`
- `MAX_SCORE_DELTA=0.15`
- `CONSERVATIVE_UNTIL_FEEDBACK_COUNT=5`
- `ALLOW_EXPORT_IMPORT=true`

Per-system application flags can disable Planning, Editing, Music, Captions, Motion, or Upload Metadata personalization independently.

## CLI Validation

Run from `D:\Olympus`:

```powershell
.\.venv\Scripts\python.exe tools\validate_creator_personalization.py --self-check
.\.venv\Scripts\python.exe tools\validate_creator_personalization.py --create-profile motivational_shorts
.\.venv\Scripts\python.exe tools\validate_creator_personalization.py --simulate --profile motivational_shorts --niche motivational
.\.venv\Scripts\python.exe tools\validate_creator_personalization.py --simulate-feedback --rating like --labels make_more_like_this,title_good
.\.venv\Scripts\python.exe tools\validate_creator_personalization.py --export-profile default
.\.venv\Scripts\python.exe tools\validate_creator_personalization.py --reset-profile default --confirm
```

Self-check and simulation modes use temporary storage. Create, export, and reset use the configured local storage unless `--storage-dir` is supplied. The tool emits `creator_personalization_validation_v2` JSON and does not render video.

## Import, Export, And Reset

Exports contain only the validated profile contract. Imports are revalidated and receive a new ID when the original ID already exists. Reset restores the profile's original safe preset, disables learning, clears learned patterns, and removes feedback associated with that profile.

## Stage Compatibility

Personalization changes invalidate only affected artifacts:

- Planning scoring/blueprint/ranking/summary stages use their personalization-aware versions.
- Editing subtitle/caption/timeline stages use their personalization-aware versions.
- Render manifest stage version is `11`.
- Upload Metadata V2 generator/artifact version is `2`.
- Optimization upload-metadata stage version is `2`; optimization pipeline version is `3`.

Older profile-free projects and renders remain readable through optional fields and safe fallbacks.

## Validation

```powershell
ruff check src tests tools
pytest
mypy src
cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

## Limitations

- Personalization is heuristic and deterministic; it does not predict audience behavior.
- Simulations prove decision changes but do not prove visible/audible changes in an existing MP4.
- A fresh pipeline run is required for a profile change to affect rendered output.
- Learning quality depends on explicit, representative feedback and remains conservative during early feedback.
- Profiles are local to the configured Olympus workspace and are not automatically shared between machines.
