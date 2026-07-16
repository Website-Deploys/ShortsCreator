# Internet Trend Research V2

Internet Trend Research V2 is a reusable, project-level intelligence layer for
Olympus. It detects a video's niche, creates a bounded public-web query plan,
loads a reusable snapshot from cache when possible, and supplies attributed
pattern guidance to Virality, Planning, Editing, unified clip metadata, and the
rendered clip card.

It does **not** predict that a clip will go viral. It does not download third-party
videos, fetch creator transcripts, copy scripts/captions/titles/thumbnails, bypass
access controls, or treat a trend pattern as more important than story truth.

## Pipeline

1. The Virality `trend_research` stage reads the transcript, Story V2 topics and
   micro-stories, project intent, and available Link Ingestion metadata.
2. `content_niche_v2` selects one of 17 canonical niches with evidence and
   confidence.
3. The query planner creates 3-5 niche/platform/safety queries and a stable cache
   key. Queries never request copied scripts, captions, downloads, or private data.
4. A fresh matching cache entry is reused. Otherwise the configured provider runs.
5. Results are reduced to short source summaries and high-level pattern objects.
6. If no live provider is configured or research fails, the engine persists an
   honest evergreen fallback snapshot.
7. Virality uses trend fit as a small advisory score. Planning keeps story/payoff
   quality primary and applies soft pattern diversity. Editing converts guidance
   into planned caption, pacing, music, SFX-density, hook-motion, and ending choices.
8. Rendering preserves the unified trend summary; render truth still determines
   whether any planned visual/audio treatment was actually applied.

## Contract and artifacts

The canonical object is `internet_trend_research_v2`. It contains:

- snapshot, creation, expiry, cache, research, provider, and fallback status;
- a stable query plan and canonical detected niche;
- platform focus and concise attributed sources;
- hook, storytelling, retention, ending, caption, pacing, audio/music, editing,
  title, hashtag, and risk patterns;
- Story V2 advisory annotations, confidence, warnings, and copyright safeguards.

Project artifact:

`trend/{project_id}/trend_research_v2.json`

Reusable cache artifact:

`work/trend_cache/trend_snapshot_{cache_key}.json`

The Virality repository also persists the stage result at its normal stage path.
The frontend/API can read the snapshot at:

`GET /api/v1/projects/{project_id}/virality/trend-research`

## Providers

- `evergreen` (default): no network call. Uses the bundled pattern library and
  clearly sets `fallback_used=true` and `cache_status=evergreen_fallback`.
- `official_source`: optional no-key refresh of a small allowlisted registry of
  official public platform guidance. Page bodies are used transiently and discarded;
  only original pattern summaries and attribution metadata persist.
- `mock`: deterministic test provider with no network access.
- `configured_web`: optional adapter for an administrator-configured HTTPS JSON
  search endpoint. Search metadata is reduced to original structural summaries;
  target pages remain disabled by default.

No paid API, Docker, WSL, account cookies, or API key is required by default.
The default remains offline. Set `provider=official_source` for no-key public official
refresh, or configure the generic search adapter explicitly. Configured-search failure
can cascade to official refresh before evergreen fallback.

## Cache behavior

- General patterns: 168 hours by default.
- Niche patterns: 72 hours by default.
- Fast music/entertainment/gaming patterns: 24 hours by default.
- Evergreen fallback: no expiry when it is the selected offline provider.
- Live refresh: `live_refreshed`; reusable cache: `cached`.
- Eligible expired live cache after refresh failure: `stale_fallback`.
- Offline structural guidance: `evergreen_fallback`.
- Expired live snapshots are never presented as fresh. Stale fallback is bounded by
  `stale_cache_allowed_hours` and does not overwrite the original live cache.

Cache keys include the research version, niche, platform focus, language, region,
and stable query-plan hash. Research runs once per project/video, not once per clip.

## Configuration

All settings use the normal `OLYMPUS_...` environment convention:

```text
OLYMPUS_TREND_RESEARCH__ENABLED=true
OLYMPUS_TREND_RESEARCH__PROVIDER=evergreen
OLYMPUS_TREND_RESEARCH__ALLOW_OFFICIAL_SOURCE_REFRESH=true
OLYMPUS_TREND_RESEARCH__ALLOW_CONFIGURED_WEB_SEARCH=false
OLYMPUS_TREND_RESEARCH__CONFIGURED_SEARCH_ENDPOINT=
OLYMPUS_TREND_RESEARCH__CONFIGURED_SEARCH_API_KEY_ENV=
OLYMPUS_TREND_RESEARCH__ALLOW_LIVE_WEB_PROVIDER=false
OLYMPUS_TREND_RESEARCH__WEB_SEARCH_ENDPOINT=
OLYMPUS_TREND_RESEARCH__WEB_SEARCH_API_KEY=
OLYMPUS_TREND_RESEARCH__CACHE_ENABLED=true
OLYMPUS_TREND_RESEARCH__CACHE_DIR=work/trend_cache
OLYMPUS_TREND_RESEARCH__MAX_QUERIES_PER_VIDEO=5
OLYMPUS_TREND_RESEARCH__MAX_SOURCES_PER_SNAPSHOT=12
OLYMPUS_TREND_RESEARCH__GENERAL_TTL_HOURS=168
OLYMPUS_TREND_RESEARCH__NICHE_TTL_HOURS=72
OLYMPUS_TREND_RESEARCH__FAST_TTL_HOURS=24
OLYMPUS_TREND_RESEARCH__STALE_CACHE_ALLOWED_HOURS=336
OLYMPUS_TREND_RESEARCH__MAX_FETCH_BYTES=250000
OLYMPUS_TREND_RESEARCH__MAX_REDIRECTS=3
OLYMPUS_TREND_RESEARCH__REQUEST_TIMEOUT_SECONDS=15
OLYMPUS_TREND_RESEARCH__FALLBACK_TO_EVERGREEN=true
```

## Validation

Offline fallback:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_trend_research.py `
  --niche motivational --offline
```

Cache-only (run offline once for the same niche first):

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_trend_research.py `
  --niche motivational --cache-only
```

Transcript metadata mode:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_trend_research.py `
  --transcript-file .\path\to\transcript.json --offline
```

Live mode uses configured search when available, otherwise the official-source provider:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_trend_research.py `
  --niche motivational --live
```

Dedicated provider self-check, official refresh, configured-search, offline, and cache
modes are documented in `docs/LIVE_RUNTIME_INTERNET_TREND_PROVIDER_V2.md`.

## Bundled public guidance

The evergreen fallback includes short, original summaries of public platform
guidance, including [YouTube Shorts search/discovery tips](https://support.google.com/youtube/answer/11914225?co=YOUTUBE._YTVideoType%3Dshorts&hl=en),
[YouTube recommendation guidance](https://support.google.com/youtube/answer/16559651?hl=en),
and TikTok's public Creative Starter Pack. These summaries are bundled reference
material; the app does not claim it fetched them during an offline run.

## Limitations

- The default runtime remains offline and therefore reports evergreen fallback.
- Official refresh is available without a paid API but must be selected explicitly.
- Search-result summaries can support only coarse pattern extraction. They are
  never a substitute for measured audience data or editorial judgment.
- Niche detection is transparent keyword/multi-signal inference, not a trained
  classifier.
- Trend guidance is planned metadata until Editing/Rendering manifests prove an
  effect was executed.
