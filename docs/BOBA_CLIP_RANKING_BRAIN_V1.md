# BOBA Clip Ranking Brain V1

## Purpose

BOBA Clip Ranking Brain V1 ranks compact candidate metadata produced by BOBA Candidate
Clip Discovery. It explains which discovered windows are strongest, which are useful
backups, which need boundary/context revision, and which should be rejected.

This is an offline advisory layer. It does not select Olympus plans, edit or render media,
call external services, predict real audience performance, or grant copyright permission.

## Existing Ranking Coexistence

Olympus already had two separate ranking concepts:

- Olympus Planning ranks planning candidates for the production pipeline.
- Legacy BOBA Core `rank_candidates` ranks Olympus planning candidates and persists
  `candidate_rankings.json`.

Clip Ranking Brain V1 does not replace either path. It consumes the newer BOBA Candidate
Clip Discovery artifact and persists a distinct `clip_ranking/index.json` contract. The
new contract remains module-qualified as `olympus.boba.clip_ranking.BobaClipRankingV1`;
the package root exports it as `BobaDiscoveryClipRankingV1` so the legacy root
`BobaClipRankingV1` stays backward compatible.

## Inputs

Candidate Discovery is required. Ranking can additionally consume:

- BOBA Whole Video Understanding section, emotion, and context/payoff signals.
- Olympus Story V2 micro-story and payoff metadata.
- Olympus Virality V2 hook, retention, and reasoning metadata.
- Olympus Planning V2 candidate/selection evidence.
- Existing BOBA project memory as a bounded preference adjustment.
- Source type and rights-confirmation status for advisory safety penalties.

Unavailable optional inputs use deterministic fallback scores and are listed in
`signal_usage.unavailable_signals`. Missing or empty Candidate Discovery fails clearly;
BOBA does not fabricate candidates.

## Output Contract

`BobaClipRankingV1` contains:

- Ranked candidates with rank, tier, total score, confidence, and production priority.
- Per-candidate score breakdown, reasons, risks, and improvement suggestions.
- Recommended, backup, and rejected candidate IDs.
- Rejected-candidate details for exact duplicates and quality/risk rejects.
- Diversity and upstream-signal usage summaries.
- Explicit warnings and limitations.

Only compact metadata is persisted. Raw frames, media, and full transcripts are excluded.

## Score Breakdown

Scores use a local deterministic 0–100 scale:

| Component | Meaning |
| --- | --- |
| Hook | Curiosity/attention cues, hook candidate type, concise hook text, and clean start |
| Payoff | Confirmed payoff, complete ending, and context/payoff coverage |
| Standalone | Existing standalone score adjusted for setup and context dependency |
| Emotional | Emotion type/cues and overlapping Whole Video emotional intensity |
| Clarity | Clear topic/story angle, upstream clarity/completeness, and warning load |
| Novelty | Upstream novelty, unique topic, and unusual candidate type |
| Pacing | Duration fit, favoring practical 25–45 second windows, plus energy evidence |
| Retention | Hook/payoff/emotion/pacing blend with available Virality retention evidence |
| Context risk | Missing setup, context dependency, or incomplete context/payoff coverage |
| Repetition penalty | Filler/repetition evidence and over-represented topics |
| Overlap penalty | Heavy overlap with a stronger discovered candidate |
| Rights/safety penalty | Unknown or denied rights for external/scout candidates |
| Memory alignment | Small bounded adjustment from explicit BOBA memory lessons |

The positive core uses hook (15%), payoff (14%), standalone (13%), emotion (9%),
clarity (11%), novelty (8%), pacing (9%), and retention (11%), normalized over that
90% core. Context, repetition, overlap, and rights penalties are then applied. Memory
only shifts the result slightly and cannot dominate source evidence. Candidate confidence
also conservatively scales the final advisory score.

The result is a BOBA advisory ranking, not a probability of virality or audience success.

## Tiering And Priority

Default tiers are:

- `must_make`: 85–100, with a confirmed payoff or very strong hook and no severe context risk.
- `strong_candidate`: 70–84.
- `backup_candidate`: 55–69.
- `needs_revision`: 40–54.
- `reject`: below 40 or an invalid/severe duplicate condition.

Production priorities are `immediate`, `high`, `medium`, `low`, and `do_not_produce`.
`immediate` requires a must-make score with low context risk and no unknown external-rights
penalty. Rights warnings never establish ownership or permission.

## Diversity, Duplicate, And Overlap Logic

- Exact duplicate IDs or exact source windows are removed before ranking.
- High-overlap lower-scoring candidates receive an explicit penalty and stronger-candidate ID.
- The final recommendation pass favors new topics, emotions, and candidate types.
- A slightly lower-scoring candidate may move earlier to preserve useful diversity; that
  choice is recorded in ranking reasons and diversity warnings.
- Severe overlapping recommendations with the same topic and type are skipped.
- The default recommendation maximum is 10, with a target of at least 3 when enough
  candidates clear the quality floor. Weak candidates are never promoted just to fill a quota.

## Persistence

Atomic local storage uses:

```text
work/boba/projects/<project_id>/clip_ranking/index.json
```

The legacy BOBA `candidate_rankings.json` artifact remains unchanged. Old projects without
the new artifact load safely and return a clear unavailable response.

## Downstream Use

- Creative Director still prefers existing selected plans and planning candidates.
- If those are unavailable, it can consume non-rejected discovered candidates in ranking order.
- Olympus Planning remains authoritative; V1 does not automatically replace or mutate plans.
- Rendering is never triggered by ranking routes or validators.

## API

Run ranking from the saved Candidate Discovery artifact:

```http
POST /api/v1/boba/projects/{project_id}/clip-ranking/rank
```

Load the saved ranking:

```http
GET /api/v1/boba/projects/{project_id}/clip-ranking
```

Both routes are local and require BOBA/candidate ranking to be enabled. GET returns a clear
404 when no ranking artifact exists.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_clip_ranking.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_clip_ranking.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_clip_ranking.py --project-id PROJECT_ID
```

Reports are written under:

```text
work/validation_reports/boba_clip_ranking/
```

Synthetic validation covers strong, weak, duplicate, high-overlap, setup-dependent,
high-payoff, high-emotion, and diverse educational candidates. It requires no media,
network, downloader, renderer, secrets, or external APIs.

## Limitations

- V1 uses transparent editorial heuristics rather than learned audience-performance data.
- Signal quality is limited by available upstream metadata.
- Memory influence is intentionally small and advisory.
- Unknown external rights produce warnings and priority limits, not legal conclusions.
- Ranking does not prove a clip is viral, copyright-safe, production-ready, or rendered.
- Human editorial and rights review remain required.
