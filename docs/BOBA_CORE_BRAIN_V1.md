# BOBA Core Brain V1

## What BOBA Is

BOBA is the local cognitive and advisory layer above Olympus' existing Story, Virality, Planning,
Editing, Rendering, Music, Metadata, Trend, Personalization, and Safety systems. Olympus remains the
execution body; BOBA observes persisted evidence, remembers bounded project reasoning, compares
options, and explains editorial recommendations.

BOBA Core Brain V1 implements the first two maturity levels:

1. **Observe** existing Olympus signals and missing evidence.
2. **Advise** with explainable candidate rankings and editorial policies.

Existing engines remain authoritative. A BOBA directive is persisted as advisory metadata and is
not automatically treated as applied.

## What BOBA Is Not

BOBA is not a chatbot, prompt wrapper, renderer, publisher, autonomous trend scraper, copyright
clearance system, DRM bypass, private-video accessor, or guaranteed-virality system. It does not
directly download, render, upload, publish, or modify media. It does not silently learn from user
behavior or send memory to a cloud service.

## Why BOBA Exists

Olympus V2 already has strong specialist engines, but important reasoning is distributed across
their artifacts. BOBA supplies a single bounded project view that can answer:

- What does Olympus actually know about this source?
- Which important signals are missing?
- Why is one clip candidate stronger than another?
- What story, hook, payoff, safety, diversity, and editing tradeoffs matter?
- How should a selected clip feel when Editing V2 eventually consumes BOBA guidance?
- Which recommendation is advisory, and which effect was actually rendered?

## Architecture

```text
Persisted Olympus artifacts
  Story / Virality / Planning / Editing / Render / Trend / Safety / Personalization
                                |
                                v
                    BOBA Integration Adapter
                                |
          +---------------------+---------------------+
          |                     |                     |
     Brain State          Candidate Ranking      Editorial Policy
          |                     |                     |
          +---------------------+---------------------+
                                |
                    Local Project Memory Store
                                |
            API inspection + compact UI metadata
```

BOBA introduces no parallel media pipeline. `BobaIntegration` reads existing JSON artifacts through
the configured `StoragePort`. Full BOBA memory lives beneath `work/boba/projects/<project_id>/`.
Only compact, optional BOBA truth belongs in `unified_clip_intelligence`.

## Constitution

`src/olympus/boba/constitution.py` is the permanent policy source. Core priorities are:

1. Safety and rights.
2. Story completeness.
3. Hook clarity.
4. Viewer retention.
5. Creator preference.
6. Trend fit.
7. Editing opportunity.
8. Diversity across clips.
9. Upload readiness.

Every material decision needs evidence, confidence, risks, tradeoffs, and a user-facing explanation.
Missing evidence must be reported rather than inferred. BOBA cannot override a Safety blocker,
declare copyright safety, copy creator scripts/titles/lyrics, fabricate trends or analytics, render
media, or publish media.

## Brain State

`BobaBrainStateV1` records:

- source understanding and signal availability;
- bounded project-memory summaries;
- decision context and known limitations;
- active advisory goals;
- decisions, observations, experiments, and project learning notes;
- honest planning/editing/rendering readiness and blockers.

The default mode is `advise`. Other mode names reserve future contract evolution but do not grant
autonomous execution in V1.

BOBA detects missing transcript, visual, face, speaker, trend, safety, personalization, and render
signals. It also preserves discovered sync, abrupt-cut, face-tracking, music, or speech-clarity
warnings when existing artifacts expose them.

## Decision Bus

`BobaDecisionBus` validates and stores directives for Story, Virality, Planning, Editing, Captions,
Music, Motion, Upload Metadata, Safety, Trend, Personalization, or Frontend. All V1 routes return:

- `delivery=advisory`;
- `consumed=false`;
- a reason explaining that existing engines remain authoritative.

Unknown consumption support never crashes the Olympus pipeline. Safety/publishing overrides are
rejected before persistence.

## Project Memory

The local store writes atomically on Windows:

```text
work/boba/projects/<project_id>/
  brain_state.json
  decisions.json
  observations.json
  learning_notes.json
  candidate_rankings.json
  editorial_policies.json
```

Memory rules:

- BOBA Core project state is fully supported; BOBA Memory System V1 now adds bounded project,
  creator, and seeded global long-term scopes under `work/boba/memory/`.
- creator/global learning is interface-only;
- all text is bounded by `max_excerpt_chars`;
- secret-like keys or credential-like text are rejected;
- raw transcript blobs, binary data, cookies, tokens, and keys are not stored;
- writes use a temporary file and `os.replace`;
- no cloud synchronization or hidden profile exists.

## Reasoning Engine

Reasoning is deterministic and offline. It converts existing numerical and categorical evidence into
editorial explanations with a summary, evidence, tradeoffs, rejected options, risks, user-facing
wording, and calibrated confidence. No external LLM is called.

The explanations deliberately avoid score-only language. A recommendation describes why hook,
story completeness, payoff, context independence, uniqueness, safety, creator fit, trend fit, and
boundary quality support or weaken a candidate.

## Candidate Ranking

BOBA's ranker is an adapter over Planning V2 candidates; it does not replace Planning V2. It checks:

- first-three-second hook evidence;
- complete story and payoff;
- curiosity and emotional movement;
- context requirement;
- temporal overlap and already-used ranges;
- source-timeline diversity;
- safety/manual-review risk;
- creator and trend fit;
- editing opportunity;
- suspicious boundaries and likely mid-sentence cuts.

Results are stored as `BobaClipRankingV1`. Low-confidence, unsafe, or highly duplicate candidates
can be listed as rejected advisory options while Planning's persisted selection remains unchanged.

## Editorial Policy

`BobaEditorialPolicyV1` recommends pacing, hook treatment, caption density, music mood/ducking,
motion restraint, clean SFX policy, silence handling, payoff-tail preservation, and safety
constraints. It always prioritizes speech, readable captions, no noise-like SFX, and avoiding a cut
on the final word. Face/layout absence disables face-dependent motion rather than pretending.

The policy is useful input for a future influence phase. Editing V2 does not automatically consume
it in Core Brain V1.

## Olympus Integration

BOBA reads the existing engine namespaces and tolerates missing or old artifacts. Render truth uses
the canonical `render/<project_id>/run/index.json` plus its
`run/stages/generate_render_manifest.json` payload, with the historical root manifest used only as
a compatibility source.

The compact optional metadata contract is:

```json
{
  "boba": {
    "brain_version": "1",
    "mode": "advise",
    "decisions_present": true,
    "ranking_explanation": "...",
    "editorial_policy_summary": "...",
    "confidence": 0.72,
    "missing_signals": [],
    "warnings": [],
    "advisory_only": true,
    "applied": false
  }
}
```

Old projects without BOBA retain an empty optional object and continue loading.

## API

The inspection-only routes never download or render media:

- `GET /api/v1/boba/projects/{project_id}/brain`
- `GET /api/v1/boba/projects/{project_id}/decisions`
- `GET /api/v1/boba/projects/{project_id}/observations`
- `POST /api/v1/boba/projects/{project_id}/summarize`
- `POST /api/v1/boba/projects/{project_id}/rank-candidates`
- `POST /api/v1/boba/projects/{project_id}/editorial-policy`

The editorial-policy endpoint accepts `{ "clip_id": "..." }`. Missing projects return a normal
404. All operations work offline.

## Frontend Display

The Results section shows a bounded BOBA project summary and optional per-render advisory summary:

- mode and confidence;
- planning/editing/rendering readiness;
- topics BOBA noticed;
- missing signals and warnings;
- ranking/editorial recommendation;
- explicit `No, advisory only` applied truth.

Older renders display `BOBA reasoning is not available for this older render.` The UI never says
BOBA guarantees virality, proves safety, or controls editing.

## Configuration

```env
OLYMPUS_BOBA__ENABLED=true
OLYMPUS_BOBA__MODE=advise
OLYMPUS_BOBA__STORAGE_DIR=work/boba
OLYMPUS_BOBA__MAX_EXCERPT_CHARS=300
OLYMPUS_BOBA__MAX_DECISIONS_PER_PROJECT=500
OLYMPUS_BOBA__ENABLE_PROJECT_MEMORY=true
OLYMPUS_BOBA__ENABLE_CANDIDATE_RANKING=true
OLYMPUS_BOBA__ENABLE_EDITORIAL_POLICY=true
OLYMPUS_BOBA__ENABLE_FRONTEND_DISPLAY=true
OLYMPUS_BOBA__ENABLE_GLOBAL_LEARNING=false
OLYMPUS_BOBA__ENABLE_AUTONOMOUS_SCOUT=false
OLYMPUS_BOBA__REQUIRE_USER_APPROVAL_FOR_SOURCES=true
OLYMPUS_BOBA__EXPLAIN_EVERY_DECISION=true
```

Autonomous scouting and global learning are hard-disabled in the typed V1 settings.

## Validation

```powershell
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_core.py --self-check
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_core.py --simulate-project
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_core.py --simulate-ranking
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_core.py --simulate-editorial-policy
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_core.py --project-id PROJECT_ID
D:\ShortsCreator-main\.venv\Scripts\python.exe tools\validate_boba_core.py --latest
```

Reports are written to `work/validation_reports/boba_core/` and clearly state that media was not
rerendered or manually reviewed.

Quality gates:

```powershell
D:\ShortsCreator-main\.venv\Scripts\python.exe -m ruff check src tests tools
D:\ShortsCreator-main\.venv\Scripts\python.exe -m pytest tests/unit/test_boba_core.py
D:\ShortsCreator-main\.venv\Scripts\python.exe -m pytest
D:\ShortsCreator-main\.venv\Scripts\python.exe -m mypy src

cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

## Safety, Copyright, and Privacy

BOBA performs technical advisory reasoning only. It cannot establish ownership, fair use, music
licenses, Content ID outcomes, or platform approval. Linked media still requires user rights
confirmation. BOBA never uses cookies, bypasses private/member-only access, copies creator text, or
stores large transcript/lyric/script text in global memory.

## Current Limitations

- BOBA is advisory and does not control Planning or Editing.
- It does not scout YouTube or other platforms.
- It does not consume real post-publication analytics.
- Creator/global memory is implemented by BOBA Memory System V1, but remains local,
  explicit-feedback-only, seeded/advisory, and non-autonomous.
- Deterministic heuristics depend on the quality of existing Olympus artifacts.
- BOBA does not fix A/V sync perception, voice delay, random abrupt cuts, face-tracking proof, or
  music audibility. Those remain separate rendering/quality work unless independently fixed.
- A valid ffprobe delta does not replace manual playback/listening review.
- A BOBA recommendation is not a claim that a clip will become viral.

## Roadmap

Future phases should advance deliberately from advice to bounded influence:

1. BOBA Whole Video Understanding V1
2. BOBA Candidate Discovery V1
3. BOBA Content Scout V1
4. BOBA Research Brain V1
5. BOBA Learning Loop V1
6. BOBA Experimentation Engine V1
7. BOBA Analytics Feedback V1
8. BOBA Creative Director V1

The recommended next phase is **BOBA Whole Video Understanding V1**, because stronger bounded
memory and cross-section narrative comparison should precede any automatic influence over Planning.
