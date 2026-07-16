# Motion Graphics / Effects V2

Motion Graphics V2 adds a deterministic, story-driven motion layer to the existing
Olympus Editing and Rendering V2 pipeline. It does not replace the timeline,
renderer, captions, face tracking, multi-speaker layout, music, or SFX systems.

## What It Does

- consumes Story, Virality, Trend, Planning, Caption, Music, SFX, face, and layout signals;
- selects a bounded motion style for each clip;
- plans a hook treatment, an optional story-turn pattern interrupt, and a payoff hold;
- renders supported effects through the existing FFmpeg filtergraph;
- preserves exact trim, FPS, audio timing, output duration, captions, music, and safe SFX;
- records safety checks and post-render filtergraph/probe validation;
- carries applied truth into `unified_clip_intelligence` and rendered clip cards.

It does not download overlays, use copyrighted visual assets, add strobe effects, or
claim subjective visual quality from metadata alone.

## Motion Styles

| Signal | Style | Default intensity |
| --- | --- | --- |
| Podcast/interview | `clean_podcast` | Low |
| Motivational | `motivational_dynamic` | Medium |
| Emotional story | `emotional_cinematic` | Low-medium |
| Education/tutorial | `educational_clarity` | Low-medium |
| Gaming/reaction | `gaming_reactive` | Medium-high |
| Comedy | `comedy_pop` | Medium |
| Music/singing | `music_performance_minimal` | Minimal |
| Serious/news/commentary | `cinematic_tension` | Low |
| Unknown | `default_clean` | Low-medium |

## Effect Grammar

The planner divides a clip into hook, setup, turn, payoff, and ending zones. It may emit:

- `hook_punch_in` for a faithful curiosity, warning, contrarian, or payoff-first hook;
- `reaction_zoom` for a gaming/reaction opening;
- `subtle_push_in` for emotional or performance-preserving motion;
- `pattern_interrupt_zoom` only when Story V2 supplies a real turning point;
- `payoff_hold` or `quote_hold` near a supported payoff.

Major effects are at least two seconds apart. Clips under 15 seconds allow at most three
major effects; clips under 30 seconds allow at most five. Zoom is capped at `1.18` by
default. There is no random recurring zoom cadence in a Motion V2 timeline.

## Hook Treatment

The first effect stays inside the first three seconds. Curiosity and warning hooks receive
a quick, smooth punch; emotional confessions receive a slow push; reactions receive one
bounded reaction zoom. Captions are composited after the motion filter, keeping text stable.

## Pattern Interrupts

Pattern interrupts require a Story V2 turn timestamp and sufficient spacing from other
major effects. Podcast, emotional, serious, and music-performance styles skip this effect.
No transition is reported as rendered unless a matching FFmpeg filter exists.

## Payoff Treatment

Payoffs receive a slow zoom/hold that ends inside the existing clip duration. The effect
does not freeze frames, stretch video, retime audio, or extend the timeline. Music payoff
swells remain owned by Music Intelligence V2.

## Safety

- Full-frame flashes and strobe effects are disabled.
- Speed ramps and freeze frames are disabled because duration-safe audio retiming is not implemented.
- Two-speaker stacks skip whole-frame zoom motion to avoid cropping either speaker.
- Sparse, low-confidence, or unavailable face tracking disables motion rather than risking a bad crop.
- Caption placement must have a known non-high collision strategy.
- Effects outside the clip or beyond density/zoom limits are removed before rendering.
- No external overlays or visual assets are required.

The contract records `motion_safety_validation`, including caption, face, layout, density,
flash, and duration checks. A skipped unsafe plan is honest; it is not marked applied.

## FFmpeg Implementation

Supported effects use the existing `zoompan` graph after crop/face/layout preparation and
before enhancement, FPS normalization, and ASS caption composition. Fast effects use a
smooth rise-and-return envelope. Slow pushes and payoff holds use a cosine easing envelope.

The renderer preserves:

- video `trim` and `setpts=PTS-STARTPTS`;
- audio `atrim` and `asetpts=PTS-STARTPTS`;
- `zoompan=d=1` and explicit FPS;
- music/SFX `amix=duration=first` behavior;
- explicit output `-t`;
- the existing rule against global `-shortest`.

## Render Truth

`motion_render_validation` compares the planned contract with the exact executed FFmpeg
filtergraph and confirms output existence, ffprobe video presence, sync, duration, and
safety. The render manifest must confirm every planned effect before `applied=true`.

Frame extraction in the CLI proves that frames exist at planned effect moments. A frame
hash is measurable evidence, not a claim that the visual edit looks premium.

## Unified Metadata and Frontend

`unified_clip_intelligence.motion_graphics` contains style, intensity, planned/rendered
effect counts, hook/payoff effects, safety status, render validation, skip reason, and
warnings. Rendered clip cards show a compact motion summary plus expandable details.

## Configuration

Environment keys use the `OLYMPUS_MOTION_GRAPHICS__` prefix. Important safe defaults:

```text
OLYMPUS_MOTION_GRAPHICS__ENABLED=true
OLYMPUS_MOTION_GRAPHICS__MAX_MAJOR_EFFECTS_UNDER_15S=3
OLYMPUS_MOTION_GRAPHICS__MAX_MAJOR_EFFECTS_UNDER_30S=5
OLYMPUS_MOTION_GRAPHICS__ENABLE_SPEED_RAMPS=false
OLYMPUS_MOTION_GRAPHICS__ENABLE_SAFE_FLASH=false
OLYMPUS_MOTION_GRAPHICS__MAX_ZOOM_SCALE=1.18
OLYMPUS_MOTION_GRAPHICS__REQUIRE_RENDER_VALIDATION=true
```

## Validation CLI

Simulate a plan:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_motion_effects.py --simulate --niche motivational --hook-category curiosity_gap
```

Validate a manifest:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_motion_effects.py --manifest path\to\manifest.json
```

Validate a rendered clip and manifest:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_motion_effects.py --rendered-file path\to\clip.mp4 --manifest path\to\manifest.json
```

Validate persisted project artifacts:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_motion_effects.py --project-id PROJECT_ID
```

Run a real local synthetic FFmpeg render:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_motion_effects.py --synthetic-render
```

## Limitations

- Source-motion analysis is currently unavailable, so it remains `unknown` unless upstream metadata supplies it.
- Speed ramps, freeze frames, micro-shake, background blur, swipe transitions, and flashes are not auto-rendered in this pass.
- Two-speaker stacks intentionally prioritize layout stability over whole-frame motion.
- Frame probes verify output and effect-time frames, not subjective professional quality.
- Real footage still requires manual playback to judge pacing, comfort, and editorial taste.
