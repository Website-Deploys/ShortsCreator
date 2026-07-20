# BOBA Explanation Engine V1

BOBA Explanation Engine V1 turns saved BOBA advisory artifacts into bounded,
source-attributed explanations. It explains why a candidate was discovered, how it was
ranked, why an editorial decision selected or rejected it, and why its editorial render
preflight is ready, needs revision, or blocked.

The engine is inspection-only. It does not download media, inspect media, edit clips,
invoke FFmpeg, trigger rendering, call external APIs or cloud AI services, establish
copyright safety, or predict audience performance.

## Inputs

The engine uses available local artifacts and continues honestly when any are missing:

- Whole Video Understanding V1 for topic, story, emotional, context/payoff, section, and
  shortability evidence.
- Candidate Clip Discovery V1 for source windows, discovery reasons, bounded transcript
  snippets, source signals, boundary guidance, confidence, and warnings.
- Clip Ranking V1 for order, total scores, score factors, penalties, tiers, diversity,
  rejection reasons, confidence, and improvement suggestions.
- Editorial Decision Engine V1 for selection, production priority, treatment directions,
  render preflight, risks, blockers, confidence, and improvement notes.
- Creative Director briefs for saved advisory treatment context.
- BOBA project memory for bounded advisory preference summaries only.
- Analysis signal health for explicit available, unavailable, failed, or fallback signals.

Missing artifacts do not cause fabricated claims. They produce missing-signal entries,
limitations, higher uncertainty, and human-review recommendations.

## Output Contract

The canonical contract is `BobaExplanationSetV1` with schema version
`boba_explanation_engine_v1`:

- `project_summary` gives an overall summary, top recommendation reason, strongest and
  weakest clip types, unavailable signals, uncertainties, and human-review notes.
- `candidate_explanations` explains saved discovery decisions.
- `ranking_explanations` explains saved score order and ranking rejections.
- `editorial_explanations` contains both editorial selection explanations and separate
  render-readiness explanations.
- `signal_explanation` records signals used, signals missing, fallbacks, effects, and
  warnings.
- `uncertainty_summary` records a low, medium, or high uncertainty level, its reasons,
  missing evidence, and recommended checks.
- `warnings` and `limitations` preserve bounded upstream caveats and engine boundaries.

Every clip explanation includes:

- clip and candidate identity;
- explanation type;
- short and detailed human-readable explanations;
- key reasons;
- bounded evidence entries;
- confidence;
- warnings and limitations.

## Evidence Rules

Each `BobaExplanationEvidenceV1` names:

- `evidence_type`;
- `source_artifact`;
- `source_field`;
- a snippet bounded to 300 characters;
- an optional saved score;
- an optional source timestamp;
- confidence.

The explanation prose may only summarize fields represented by the supplied artifacts.
Transcript evidence is limited to at most three bounded snippets per discovery explanation.
The full transcript is not copied into the explanation artifact. Local absolute paths,
media blobs, and raw source artifacts are not embedded.

## Uncertainty

Uncertainty increases when:

- Whole Video Understanding, Candidate Discovery, Clip Ranking, or Editorial Decisions are
  unavailable;
- transcript or analysis-provider evidence is unavailable;
- an upstream artifact declares fallback or synthetic limitations;
- clip explanations have low confidence;
- unresolved warnings accumulate.

Even a low-uncertainty explanation remains advisory. Human review must compare it with the
original source meaning, verify complete setup/payoff boundaries, and confirm rights and
technical readiness independently.

## Persistence

The canonical local artifact is:

```text
work/boba/projects/<project_id>/explanation/index.json
```

`BobaMemoryStore` writes it atomically and validates it through the typed contract when
loading. The artifact is JSON-safe and contains bounded summaries rather than full upstream
blobs.

## API

When BOBA is enabled, the inspection API exposes:

```text
POST /api/v1/boba/projects/<project_id>/explanations
GET  /api/v1/boba/projects/<project_id>/explanations
```

`POST` generates explanations from currently saved local BOBA artifacts and persists the
result. `GET` returns the saved artifact or a clear not-found response. Neither endpoint
starts editing or rendering.

## Frontend

The project Results view includes a BOBA Explanation Engine panel after Editorial Decisions.
It displays:

- project summary and top recommendation;
- uncertainty level;
- strongest and weakest clip types;
- used and missing signals;
- grouped discovery, ranking, editorial, rejection, and readiness explanations;
- evidence source artifact and field names;
- warnings, limitations, fallbacks, and human checks.

The panel explicitly says that it uses saved metadata only and does not prove rendering or
audience performance.

## Validation

Run the local self-check:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_explanation_engine.py --self-check
```

Run the fuller synthetic project case:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_explanation_engine.py --synthetic-project
```

Inspect or generate an explanation for an existing local project:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_explanation_engine.py `
  --project-id <project_id>
```

Existing-project mode reads local artifacts only. Missing evidence is reported rather than
replaced. Reports are generated under ignored `work/validation_reports/` and must not be
committed.

## Limitations

- Explanation quality cannot exceed the quality and completeness of saved upstream evidence.
- Confidence is inherited and summarized; it is not calibrated against real audience data.
- Render readiness is an editorial preflight, not proof of a valid MP4 or successful render.
- Memory is advisory and cannot override source evidence.
- Rights and copyright status require independent human confirmation.
- The engine does not provide human-level semantic review of source intent or context.
