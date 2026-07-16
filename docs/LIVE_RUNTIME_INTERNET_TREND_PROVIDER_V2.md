# Live Runtime Internet Trend Provider V2

Live Runtime Internet Trend Provider V2 is the optional public-web source layer for the existing
Internet Trend Research V2 engine. It can refresh a small registry of official guidance pages or
query an administrator-configured JSON search endpoint, then reduces the evidence to attributed,
high-level structural patterns.

It does not predict virality, download videos, scrape creator pages, collect scripts, copy titles or
captions, store article bodies, use cookies or accounts, bypass access controls, or require a paid API.
The default provider remains the offline evergreen library.

## Provider Types

- `evergreen`: default offline provider. It performs no network request and reports
  `evergreen_fallback`.
- `official_source`: optional HTTP refresh of the small allowlisted registry in
  `src/olympus/trends/sources.py`.
- `configured_web`: optional generic HTTPS JSON search adapter. It is disabled until an endpoint is
  explicitly configured. The legacy provider name remains supported.
- `mock`: deterministic tests only; it never claims internet availability.
- `disabled`: explicit unavailable provider when trend research is disabled.

When configured search is selected, Olympus can cascade to the official-source provider if configured
search is unavailable or returns no safe result. If live providers fail, the engine uses an eligible
stale attributed snapshot or the evergreen fallback and records the reason.

## Official-Source Refresh

The official registry contains only a few updateable public platform guidance URLs. A refresh:

1. validates the scheme, host, domain policy, DNS result, redirects, content type, and byte limit;
2. performs a normal unauthenticated request with no cookies;
3. uses the page body transiently to confirm that useful public text was returned;
4. discards the body;
5. persists the registry's original pattern-level summary, retrieval metadata, and attribution.

A successful fetch proves only that public evidence was retrieved during that run. It does not prove
that a specific pattern is popular, guarantee a platform outcome, or authorize copied creative work.

## Configured Search

The configured provider expects either a top-level result list or:

```json
{
  "results": [
    {
      "title": "Source title",
      "url": "https://allowed.example/source",
      "snippet": "Short search metadata",
      "published_date": "2026-07-01T00:00:00Z"
    }
  ]
}
```

Search snippets are used transiently to identify canonical Olympus pattern identifiers. They are not
persisted verbatim. Result pages are not fetched unless `FETCH_CONFIGURED_RESULT_PAGES=true`, and even
then only allowlisted public text pages are read transiently and discarded.

No particular commercial search vendor is required. If an endpoint or required key is missing, the
provider reports `CONFIGURED_SEARCH_NOT_CONFIGURED` instead of pretending live research ran.

## Source Safety and SSRF Controls

The HTTP layer rejects:

- non-HTTP(S) schemes, URL credentials, and nonstandard ports;
- localhost, single-label internal hosts, private/link-local/loopback/reserved IPs;
- internal and reserved hostname suffixes;
- blocked or non-allowlisted source domains;
- redirects to unsafe hosts;
- DNS answers containing any non-public address;
- login/access-restriction pages, unsupported content types, oversized responses, and excessive
  redirects.

The configured search endpoint must be HTTPS and public. It is administrator-configured and therefore
is not restricted to the content-source allowlist, but private/internal destinations remain rejected.
DNS validation reduces SSRF risk; as with any hostname-based client, infrastructure-level DNS pinning
is still recommended for hostile deployment environments.

## Credibility and Recency

Every persisted source includes provider, domain, source type, retrieval time, optional publication
time, credibility level, numeric credibility, recency score, supported pattern IDs, warnings, and an
original bounded summary.

- High: official platform documentation and official creator guidance.
- Medium: dated reputable industry or creator-education reports.
- Low: ordinary public articles with limited authority.
- Unknown: unrecognized or weakly attributed metadata.

Snapshot and pattern confidence use both credibility and recency. A fresh HTTP retrieval does not
invent a publication date; undated living official guidance receives a conservative recency score.

## Pattern Extraction

Olympus maps transient source signals to the existing canonical pattern library. Persisted patterns
contain generic labels, descriptions, example structures, attribution IDs, confidence, recency, safety
notes, and the existing do-not-copy warning. Exact scripts, captions, titles, thumbnails, lyrics, and
creator-specific examples are not retained.

## Cache Behavior

- `live_refreshed`: a live provider returned usable evidence in this run.
- `cached`: a fresh reusable snapshot was served; no network request ran.
- `stale_fallback`: live refresh failed and an expired attributed snapshot was still inside the
  configured stale window.
- `evergreen_fallback`: only bundled offline guidance was used.
- `failed`: no live, stale, or evergreen guidance was available.

Cache keys include Trend Research V2 version, niche, platform focus, language, region, query plan, and
provider scope. Live-refresh failures are cached only for the minimum refresh interval, so a temporary
failure cannot become a permanent fallback. Stale fallback does not overwrite the original live cache.

## Snapshot Truth

`internet_trend_research_v2` now preserves:

- `provider_requested`, `provider_used`, and `provider_status`;
- `internet_available`, `live_research_attempted`, and `live_research_succeeded`;
- `cache_status`, `fallback_used`, and `fallback_reason`;
- source count, domains, credibility summary, bounded sources, and extracted patterns;
- confidence, provider diagnostics, safety notes, and warnings.

`internet_available=true` is set only after real provider HTTP succeeds. Cached, stale, mock, evergreen,
and disabled runs report it as false.

## Configuration

```text
OLYMPUS_TREND_RESEARCH__ENABLED=true
OLYMPUS_TREND_RESEARCH__PROVIDER=evergreen
OLYMPUS_TREND_RESEARCH__ALLOW_OFFICIAL_SOURCE_REFRESH=true
OLYMPUS_TREND_RESEARCH__ALLOW_CONFIGURED_WEB_SEARCH=false
OLYMPUS_TREND_RESEARCH__CONFIGURED_SEARCH_ENDPOINT=
OLYMPUS_TREND_RESEARCH__CONFIGURED_SEARCH_API_KEY_ENV=
OLYMPUS_TREND_RESEARCH__CONFIGURED_SEARCH_PROVIDER_NAME=custom
OLYMPUS_TREND_RESEARCH__FETCH_CONFIGURED_RESULT_PAGES=false
OLYMPUS_TREND_RESEARCH__CACHE_ENABLED=true
OLYMPUS_TREND_RESEARCH__CACHE_DIR=work/trend_cache
OLYMPUS_TREND_RESEARCH__STALE_CACHE_ALLOWED_HOURS=336
OLYMPUS_TREND_RESEARCH__LIVE_REFRESH_MIN_INTERVAL_HOURS=12
OLYMPUS_TREND_RESEARCH__MAX_FETCH_BYTES=250000
OLYMPUS_TREND_RESEARCH__REQUEST_TIMEOUT_SECONDS=15
OLYMPUS_TREND_RESEARCH__MAX_REDIRECTS=3
OLYMPUS_TREND_RESEARCH__SOURCE_ALLOWLIST_ENABLED=true
```

Use `PROVIDER=official_source` to opt into no-key official refresh. Use
`PROVIDER=configured_web` plus `ALLOW_CONFIGURED_WEB_SEARCH=true` for a configured endpoint. The API key
setting contains an environment-variable name, not the key itself. Legacy `WEB_SEARCH_ENDPOINT`,
`WEB_SEARCH_API_KEY`, and `ALLOW_LIVE_WEB_PROVIDER` settings remain compatible.

## Validation CLI

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_live_trend_provider.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_live_trend_provider.py --offline --niche motivational
D:\Olympus\.venv\Scripts\python.exe tools\validate_live_trend_provider.py --official-source --niche motivational --force-refresh
D:\Olympus\.venv\Scripts\python.exe tools\validate_live_trend_provider.py --configured-search --niche podcast_interview
D:\Olympus\.venv\Scripts\python.exe tools\validate_live_trend_provider.py --cache --niche motivational
```

Use `--report-dir D:\Olympus\work\validation_reports\live_trends` to control report output. The tool
writes a mode-specific JSON report and a latest-report JSON file.

The existing validator also supports a real official-source attempt:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_trend_research.py --niche motivational --live
```

## Frontend Meanings

- Live: this run successfully retrieved public evidence.
- Cached: a fresh stored snapshot was reused; no current network request occurred.
- Stale: an expired attributed snapshot was used because refresh failed.
- Fallback: evergreen guidance was used.
- Unavailable: no usable guidance was produced.

Rendered clip cards also show provider, source count, domains, confidence, and warnings. Existing
Virality, Planning, Editing, and unified metadata consumers continue using the same pattern fields.

## Limitations

- Official URLs can move, reject automated requests, or expose insufficient public text.
- Pattern extraction is deterministic and structural, not a semantic claim that a topic is popular.
- The generic search adapter cannot normalize every vendor response shape.
- No provider guarantees virality, platform acceptance, monetization, or audience performance.
- No creator videos, scripts, captions, titles, thumbnails, song lyrics, private pages, or paywalled
  content are collected.
- Live research can be disabled at any time; offline fallback remains available.
