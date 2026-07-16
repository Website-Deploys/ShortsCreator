# Captions / Typography V2

## 1. Scope

Captions / Typography V2 is an additive upgrade to Olympus' existing ASS caption path. It does
not replace Editing V2 or Rendering V2. It converts transcript timing plus existing Story,
Virality, Planning, face-layout, and speaker signals into caption events that FFmpeg/libass burns
into the final MP4.

## 2. Audit Findings

Before this pass, Olympus generated real ASS captions, but normal render cues retained only
`start`, `end`, and `text`. Planned highlighted words, style, animation, speaker, and timing-source
fields were discarded. The ASS generator then applied one mostly fixed Arial style and fixed lower
placement. Whisper word timestamps were persisted but caption timing was estimated from whole
segments without reporting that estimation. Render metadata did not prove that the ASS file,
subtitles filter, output file, and manifest all agreed.

## 3. Pipeline Contract

The canonical `caption_intelligence_v2` object is produced during Editing V2 and travels through
the existing timeline, renderer metadata, render manifest, unified clip intelligence, real-video
validator, and frontend clip card. It contains:

- input signals and their availability
- style and typography decision
- timing plan and timing quality
- hook and selective emphasis plans
- speaker-caption decision
- face/layout-safe placement
- ASS render plan and event counts
- readability and render validation
- explicit warnings and fallback reasons

No parallel caption pipeline is introduced.

## 4. Timing Honesty

When valid transcription word timestamps exist, caption events preserve those timestamps and use
`source=word_level`, `estimated=false`. When only segment timing exists, Olympus proportionally
distributes compact phrase captions and records `source=estimated`, `estimated=true`, plus a
warning. If captions are disabled or no valid text/timing exists, no events are fabricated and the
contract reports unavailable/disabled truth.

Caption units target short mobile-readable phrases, bounded display duration, and non-overlapping
events. Seven words is a per-line target rather than a whole-caption limit; a caption may use up to
two lines when extra words are necessary to make a dense spoken burst readable. Dense runs can
look ahead across multiple adjacent events, but merge only when the result stays within the
two-line, visual-width, and maximum-duration limits and meets the timing-source reading-speed
threshold. If a readable merged run would wrap beyond two lines at the configured mobile font
size, it is rebalanced into adjacent word-timed events instead. Real word timestamps remain
attached. Transcript words cut by the selected clip boundary are omitted and reported instead of
being displayed as misleading partial tail captions. Word-level karaoke animation is only
eligible when real word timings exist.

## 5. Style Presets

Caption style follows existing niche/category/planning/trend signals with deterministic fallbacks:

- `motivational_impact`
- `clean_podcast`
- `educational_clear`
- `emotional_soft`
- `gaming_energy`
- `music_minimal`
- `comedy_pop`
- `cinematic_quote`
- `bold_hook`
- `default_clean`

Each preset controls font size, outline, shadow, accent, casing, and restrained animation. The
renderer defines separate ASS styles for normal, hook, emphasis, quote, top speaker, and bottom
speaker events.

## 6. Hook And Emphasis

The first faithful transcript caption in the first three seconds can receive a stronger hook style
and clean pop/scale animation. Candidate highlight words come from existing Story, Virality, and
Planning guidance, then intersect with words actually present in each spoken caption. Olympus does
not insert hook words that were not spoken. Filler words and overemphasis are rejected. Payoff
captions can receive a restrained quote hold and selective payoff emphasis.

## 7. Safe Placement

Caption placement consumes the real face/layout plan when available:

- single-face or active-speaker tracking uses the opposite safe region
- reliable two-speaker stacks use speaker-specific top/bottom styles
- two-speaker stacks without associations use a divider-safe shared position
- multi-face framing uses a group-safe position
- missing or unreliable face data uses a platform-safe lower fallback with a warning

Safe-zone fallback is reported; it is never presented as face-aware placement.

## 8. Speaker Captions

Speaker-aware top/bottom placement requires diarized speaker labels, a two-speaker layout, and a
speaker-to-face association confidence of at least `0.60`. Labels remain anonymous (`Speaker 1`,
`Speaker 2`); Olympus does not infer real identities. Missing or weak associations fall back to a
shared safe position and record the reason.

## 9. ASS And Render Truth

`build_ass` escapes transcript control characters, validates required ASS sections, emits named
styles, validates event timestamps/style references, and limits visual overrides. FFmpeg receives
the temporary ASS path through the existing Windows-safe subtitles filter escaping.

`caption_render_validation.passed=true` requires all of the following:

- captions were planned
- a non-empty valid ASS file was created
- ASS event/style counts were recorded
- the FFmpeg subtitles filter was present
- the rendered output file existed
- the render manifest confirmed the burned-in caption status

The renderer records technical proof first. The manifest stage is the only stage that sets
`render_manifest_confirmed=true`.

## 10. Configuration And Fonts

Configuration uses `caption_intelligence` and `caption_fonts` in Olympus settings. Defaults prefer
word-level timing, allow explicitly marked estimation, cap captions at seven words per line and two
lines, and enable hook, keyword, speaker, face-safe, readability, and render validation.

Olympus uses configured system font-family names (`Arial`, then `Segoe UI` and `Verdana` fallbacks).
It does not download, bundle, expose, or assume licensing rights to font files. Custom font paths
remain disabled by default.

## 11. Validation

Backend validation:

```powershell
.\.venv\Scripts\ruff.exe check src tests tools
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\mypy.exe src
```

Frontend validation:

```powershell
cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

Caption validator examples:

```powershell
.\.venv\Scripts\python.exe tools\validate_caption_typography.py --simulate --niche education_tutorial
.\.venv\Scripts\python.exe tools\validate_caption_typography.py --ass-file work\captions.ass
.\.venv\Scripts\python.exe tools\validate_caption_typography.py --rendered-file work\clip.mp4 --manifest work\manifest.json
.\.venv\Scripts\python.exe tools\validate_caption_typography.py --project-id PROJECT_ID
```

The CLI exits non-zero when the selected validation mode cannot prove its required result. Project
mode evaluates every timeline/render pair, lists failed clip IDs, and requires both render proof
and caption readability to pass for every rendered clip. Readability output includes per-event
duration, line count, word/character speed, timing source, and failure reasons while retaining the
legacy warning arrays for backward compatibility.

## 12. Limitations And Review

- Estimated word timing is not true forced alignment and remains labeled estimated.
- Font family availability is resolved by libass/system configuration; no font file is bundled.
- Face-aware placement is only as reliable as upstream face/layout data.
- Speaker-aware placement does not identify people and requires reliable associations.
- Structural ASS and render proof cannot guarantee subjective typography quality.
- Final visual quality still requires extracted-frame or manual playback review of a real rendered
  MP4. The report must state clearly when manual playback was not performed.
