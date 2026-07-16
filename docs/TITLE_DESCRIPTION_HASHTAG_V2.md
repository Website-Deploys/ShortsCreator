# Title / Description / Hashtag V2

Upload Metadata V2 creates deterministic, copy-ready platform metadata for each finished Olympus
render. It uses the clip's persisted Story, Virality, Planning, Editing, Trend, caption, and Copyright /
Safety signals. It does not fetch creator captions, copy viral titles, publish content, or predict
platform performance.

## Canonical Flow

1. Editing persists the selected hook, story/payoff guidance, niche, caption emphasis, trend truth,
   music role, motion style, and unified clip intelligence.
2. Rendering produces and verifies the real MP4.
3. `generate_render_manifest` generates `upload_metadata_v2` from the final clip intelligence and
   final Copyright / Safety report.
4. The full artifact is written to
   `render/<project_id>/metadata/<clip_id>/upload_metadata_v2.json`.
5. A bounded `upload_metadata` summary is added to `unified_clip_intelligence` for API and frontend
   use.
6. Optimization reuses the render artifact. For an older manifest, it can create a deterministic
   backfill without modifying the MP4.

Metadata generation and artifact persistence are isolated per clip. A metadata error is reported as
`unavailable`; it does not invalidate or delete a successfully rendered MP4.

## Contract

`upload_metadata_v2` contains:

- stable project, clip, render, version, time, status, and artifact identity;
- bounded input-signal provenance;
- YouTube Shorts title, ranked title variants, description, hashtags, and pinned-comment idea;
- Instagram Reels caption, variants, and hashtags;
- TikTok caption, variants, and hashtags;
- universal best-title, keyword, review, readiness, and warning fields;
- nested title, description, hashtag, platform, safety, copying, and spam validation.

The full artifact intentionally excludes full transcripts, fetched source bodies, creator scripts, and
raw local filesystem paths.

## Platform Rules

### YouTube Shorts

- Titles are normally limited to 70 characters.
- Descriptions remain one to three short lines.
- Hashtags are limited to eight; niche tags precede the platform tag and focused topic tags.
- Up to five ranked title candidates are retained for manual A/B testing.

### Instagram Reels

- Captions are slightly more conversational and may ask one thoughtful, non-manipulative question.
- Hashtags are limited to twelve and mix niche, platform, topic, and supported emotional context.

### TikTok

- Captions are shorter and more direct.
- Hashtags are limited to eight.
- `#FYP`, false trend tags, challenge tags, and unrelated discovery tags are not defaulted.

## Title and Caption Generation

Titles use a cleaned clip title or hook when it is bounded and does not contain prohibited claims.
Additional variants use the hook category only as a structural signal. Curiosity, warning, education,
podcast, gaming, performance, and emotional patterns are phrased around clip-derived keywords; they
do not invent people, outcomes, high notes, reactions, or events.

Descriptions and captions summarize the known topic and story/payoff shape. The pinned-comment idea
asks for a thoughtful opinion. Olympus does not emit `like if`, forced-comment, or share-pressure
engagement bait.

## Hashtag Planning

Hashtags come from:

- the detected niche;
- caption-emphasis and bounded hook keywords;
- supported story emotion;
- the target platform format.

The planner normalizes casing, removes duplicates, enforces platform limits, rejects invalid or
noise-like tokens, and records removed-tag reasons. It does not convert matched trend patterns into
hashtags, because a pattern match alone does not establish that a tag is current or relevant.

## Safety and Trend Truth

The final Copyright / Safety report controls metadata readiness:

- `low` with `ready_with_low_risk` can produce a validated ready state;
- `medium`, `high`, or `unknown` requires a visible manual-review warning;
- `blocked` or `not_ready` keeps generated copy for review but marks validation failed and upload
  readiness false.

This is a technical risk workflow, not legal advice. Olympus never labels output "copyright safe".

Trend provenance is retained in `input_signals`: provider, cache status, live research result, source
count, matched high-level patterns, and confidence. Fallback research never claims to be live or
current, and no output is described as guaranteed viral.

## Validation

Validation rejects or warns on:

- empty or over-limit titles;
- all-caps titles and excessive punctuation;
- prohibited claims and manipulative engagement bait;
- long passages copied from the supplied source text;
- long source reproduction for music/singing metadata;
- duplicate, blocked, or over-limit hashtags;
- missing safety warnings or manual-review state;
- blocked safety readiness.

Fewer-than-target hashtags produce a warning rather than unrelated filler tags.

## Frontend

Each rendered clip card shows an **Upload Metadata** section with:

- best title and validation/review badge;
- copy buttons for title, full YouTube copy, full Instagram copy, full TikTok copy, and hashtags;
- platform-specific descriptions/captions and hashtag sets;
- ranked title variants;
- visible safety or validation warnings;
- a safe unavailable message for older renders.

## CLI

Run from `D:\Olympus`:

```powershell
.\.venv\Scripts\python.exe tools\validate_upload_metadata.py --simulate --niche motivational --hook-category curiosity_gap
.\.venv\Scripts\python.exe tools\validate_upload_metadata.py --sample-transcript "This is why discipline matters when nobody is watching." --niche motivational
.\.venv\Scripts\python.exe tools\validate_upload_metadata.py --metadata-file path\to\upload_metadata_v2.json
.\.venv\Scripts\python.exe tools\validate_upload_metadata.py --manifest path\to\render\index.json
.\.venv\Scripts\python.exe tools\validate_upload_metadata.py --project-id PROJECT_ID
```

`--project-id` reads `render/<project_id>/index.json` beneath the configured local storage root. The
tool performs no publishing and no network access.

## Configuration

Environment variables use the `OLYMPUS_UPLOAD_METADATA__` prefix. Operators can enable platforms,
set title and hashtag limits, disable emoji, control title variants, and require safety/manual-review
disclosure. Misleading-claim and spam-tag blocks remain enabled by default.

## Limitations

- Generation is deterministic and does not perform semantic fact-checking beyond persisted Olympus
  signals and conservative language rules.
- It cannot establish ownership, fair use, platform approval, or Content ID outcomes.
- It does not identify people or add celebrity names.
- It does not test real-world click-through rate or guarantee reach.
- Human review remains necessary for uncertain source rights, nuanced claims, names, medical/legal/
  financial context, and any blocked or unknown safety result.
