# Olympus Copyright / Safety Checker V2

> This is a technical risk assessment, not legal advice.

Copyright / Safety Checker V2 evaluates provenance and license metadata already available to
Olympus. It does not determine ownership, fair use, legal approval, Content ID outcomes, or final
platform moderation decisions. Use only source media and assets you own or have permission to use.

## What It Does

- checks source type, URL provenance, restrictions, and persisted rights confirmation;
- checks the actual selected music asset and its local Music Library V2 license metadata;
- checks mixed SFX and future visual assets for license and generated provenance;
- applies conservative caption/text warnings without storing transcript or lyric excerpts;
- aggregates the ingredients present in a rendered clip;
- produces platform-readiness warnings for YouTube Shorts, Instagram Reels, and TikTok;
- creates a bounded manual-review checklist;
- preserves a compact result in `unified_clip_intelligence`;
- writes fixed JSON and Markdown validation reports.

## What It Does Not Do

The checker does not:

- bypass DRM, authentication, age gates, private/member-only access, or regional restrictions;
- use cookies or credentials to download restricted content;
- remove watermarks or conceal source/music use;
- recommend cropping, speeding, pitch shifting, noise, or other evasion techniques;
- download music or scrape streaming platforms;
- reproduce lyrics, scripts, large transcript excerpts, or creator captions;
- label content as fair use, legally approved, guaranteed accepted, or Content ID-proof.

## Risk Levels

| Level | Meaning |
| --- | --- |
| `low` | Available metadata indicates low technical risk; it is not a legal guarantee. |
| `medium` | Permission or license scope is incomplete and needs manual review. |
| `high` | A serious provenance, attribution, or license problem should be resolved first. |
| `blocked` | A configured hard condition prevents automatic clearance or rendering. |
| `unknown` | Important source or asset metadata is unavailable. |

## Upload Readiness

- `ready_with_low_risk`
- `needs_manual_review`
- `not_ready`
- `blocked`
- `unknown`

These statuses describe local technical evidence only. They do not predict a platform decision.

## Source Video Checks

Link ingestion already rejects unsupported hosts, private/login-only media, age restrictions, DRM,
and missing rights confirmation. The checker reads the persisted link-ingestion record when
available. A public YouTube link is never considered low risk merely because it was downloadable.

- verified public-domain or Creative Commons metadata can lower risk;
- user-confirmed third-party links normally remain `medium` with manual review;
- missing required link confirmation is `blocked`;
- a local upload with an explicit owner/permission basis can be `low`;
- an older local upload without that basis is `unknown`, not automatically cleared.

## Music Checks

Music truth comes from Music Library V2 and actual render metadata. Automatic use requires a
known license, `license_verified=true`, `safe_default=true`, acceptable source metadata, successful
quality validation, and complete attribution when required. Streaming-platform sources and missing
licenses are blocked for automatic use.

Generated Olympus music has low technical provenance risk but remains validation-quality starter
music. The report retains that warning and does not describe it as curated production music.

## SFX and Visual Assets

Generated local SFX are checked through their `generated://olympus/...` provenance, declared
license, usage permission, and safe-default metadata. Noise-like rejection remains owned by
Editing/Rendering V2. Unknown or unlicensed SFX and visual assets are blocked for automatic use.

Olympus currently has no external overlay/template library. Therefore visual assets normally report
`used=false`; future overlays must provide the same per-asset provenance fields before automatic use.

## Captions and Text

Transcript-derived captions normally inherit the source assessment. The checker records only risk
booleans and warnings. It does not persist report excerpts. Conservative heuristics flag explicit
copied-text metadata, marked lyrics/music sources, repeated lyric-like lines, and excessive quoted
text. These are review signals, not perfect copyright detection.

## Render Integration

Rendering performs two checks:

1. **Pre-render:** evaluates source/link rights and planned metadata. A configured `blocked`
   condition stops FFmpeg before output is created.
2. **Post-render:** evaluates the actual resolved music/SFX and rendered composition, then stores
   `copyright_safety_v2` in the rendered clip metadata and manifest.

The compact `unified_clip_intelligence.copyright_safety` section carries risk, readiness, source
confirmation, music/SFX license status, manual-review state, blocked reasons, warnings, and the
disclaimer. Older renders without this metadata remain loadable and display `Not available`.

## Platform Readiness

Platform entries provide readiness, warnings, blocked reasons, and manual-review state. The
YouTube entry also checks basic vertical short-form shape and a conservative duration boundary when
render dimensions/duration are available. Platform requirements can change, so users must verify
current publishing rules themselves.

No platform entry claims that a clip will pass Content ID or moderation.

## Manual Review Checklist

When review is required, the report asks the user to confirm:

- ownership or permission for the source video;
- target-platform permission for music;
- required attribution;
- provenance for SFX, overlays, templates, logos, and footage;
- that captions/title/description do not copy another creator's script;
- that the edit is not misleading, impersonating, private, or restricted.

## Configuration

Defaults are conservative:

```env
OLYMPUS_COPYRIGHT_SAFETY__ENABLED=true
OLYMPUS_COPYRIGHT_SAFETY__WARN_ONLY=false
OLYMPUS_COPYRIGHT_SAFETY__BLOCK_ON_BLOCKED=true
OLYMPUS_COPYRIGHT_SAFETY__BLOCK_ON_HIGH_RISK=false
OLYMPUS_COPYRIGHT_SAFETY__REQUIRE_RIGHTS_CONFIRMATION_FOR_LINKS=true
OLYMPUS_COPYRIGHT_SAFETY__REQUIRE_MUSIC_LICENSE_VERIFIED=true
OLYMPUS_COPYRIGHT_SAFETY__REQUIRE_SFX_LICENSE_VERIFIED=true
OLYMPUS_COPYRIGHT_SAFETY__REQUIRE_VISUAL_ASSET_LICENSE_VERIFIED=true
OLYMPUS_COPYRIGHT_SAFETY__WARN_ON_UNKNOWN_SOURCE=true
OLYMPUS_COPYRIGHT_SAFETY__WARN_ON_GENERATED_VALIDATION_MUSIC=true
OLYMPUS_COPYRIGHT_SAFETY__REQUIRE_MANUAL_REVIEW_FOR_THIRD_PARTY_LINKS=true
OLYMPUS_COPYRIGHT_SAFETY__MAX_REPORT_TEXT_EXCERPT_CHARS=300
```

`block_on_blocked=true` is the default hard floor. `high` risk warns and reports `not_ready` but does
not block unless `block_on_high_risk=true`. `warn_only=true` disables enforcement while retaining
the calibrated report. Disabling the checker produces an explicit `unknown` report rather than a
false pass.

## CLI Commands

Run from PowerShell at `D:\Olympus`:

```powershell
.\.venv\Scripts\python.exe tools\validate_copyright_safety.py `
  --project-id PROJECT_ID

.\.venv\Scripts\python.exe tools\validate_copyright_safety.py `
  --rendered-file path\to\clip.mp4 `
  --manifest path\to\manifest.json

.\.venv\Scripts\python.exe tools\validate_copyright_safety.py --music-library

.\.venv\Scripts\python.exe tools\validate_copyright_safety.py `
  --source-url "https://www.youtube.com/watch?v=VIDEO_ID" `
  --rights-confirmed

.\.venv\Scripts\python.exe tools\validate_copyright_safety.py `
  --simulate --source third_party_youtube --music generated_safe
```

`--source-url` never fetches the URL. It evaluates only the supplied URL and confirmation flag.
Project mode reads the local storage repository. Manifest mode requires an existing rendered file.

## Reports

Default output directory:

`work\validation_reports\copyright_safety`

Files:

- `copyright_safety_report.json`
- `copyright_safety_summary.md`

The JSON contains `copyright_safety_v2`, optional per-clip/project/library detail, validation mode,
and the disclaimer. The Markdown report includes the aggregate status, component flags, warnings,
and manual-review checklist.

## Frontend

Rendered clip cards show:

- risk level and upload readiness;
- whether manual review is required;
- source-rights confirmation status;
- music and SFX license status;
- blocked/warning reason;
- the technical-assessment disclaimer.

The UI intentionally uses `low risk`, `needs review`, and `blocked` language rather than promising
copyright or platform approval.

## Validation

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m mypy src

cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

## Limitations

- User confirmation is evidence, not independent proof of ownership or license scope.
- Unknown licenses cannot be verified automatically.
- Heuristics cannot perfectly identify copied text, lyrics, logos, game footage, film/TV footage,
  or derivative-work risk.
- No local checker can know a future Content ID, takedown, monetization, or moderation decision.
- A low-risk report does not replace creator review or qualified legal advice.
