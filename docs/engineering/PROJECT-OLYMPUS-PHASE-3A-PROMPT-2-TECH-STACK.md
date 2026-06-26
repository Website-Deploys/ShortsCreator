# Project Olympus — Phase 3A / Prompt 2

## Technology Stack, AI Model Selection & Engineering Decisions

**Status.** The MVP Engineering Architecture (Phase 3A) is final. This document does not change it. It *populates* every role defined there with the best concrete technology available today, chosen for reliability, scalability, maintainability, performance, developer experience, cost, and future flexibility — not novelty.

**Authoring stance.** Written as the CTO's technology decision record: opinionated, concrete (real products, languages, frameworks, model categories with named examples), and justified. Every major decision states alternatives considered, advantages, disadvantages, and a migration path. The bias throughout is toward *boring, proven, replaceable* technology over trendy, unproven, lock-in technology.

**A note on "best."** "Best" here never means "newest." It means the choice that maximizes the weighted sum of reliability, total cost of ownership, team velocity, and optionality over a multi-year horizon. Where a managed service buys reliability and speed for the MVP at a cost we can later optimize away, we take it — *behind a replaceable interface* (the architecture's seams), so the convenience now never becomes the cage later.

---

# Part 1 — Technology Selection Philosophy

## 1.1 The principles

Every technology choice in this document is scored against nine criteria, in roughly this priority order:

1. **Reliability.** Does it work correctly, predictably, under load, and at the edges? Olympus runs creators' real work through long pipelines; an unreliable component anywhere poisons the whole product. Reliability is weighted highest.
2. **Maturity.** Has it been battle-tested in production by many organizations for years? Mature technology has had its sharp edges found and filed by others. We strongly prefer technology that is *boring* — whose failure modes are documented and whose behavior is predictable.
3. **Ecosystem.** Are there robust libraries, integrations, tooling, and hiring pools around it? A rich ecosystem means most problems are already solved and most hires already know it.
4. **Performance.** Is it fast and efficient *enough* for our actual workload (not benchmarks)? We optimize for real throughput and latency in *our* pipeline, not abstract speed.
5. **Scalability.** Can it grow with us without a rewrite? We choose technology whose scaling path we understand in advance.
6. **Community support.** Is there an active community, so problems are answerable and the technology won't be abandoned?
7. **Documentation.** Can a new engineer become productive quickly? Good docs are a multiplier on team velocity.
8. **Replacement cost.** If we had to swap it out, how painful would it be? We prefer technology that sits behind a clean interface and adheres to open standards, so replacement is cheap. This criterion is what protects us from our own early choices.
9. **Long-term maintenance.** What is the ongoing operational and cognitive burden? We prefer fewer moving parts, fewer languages, fewer bespoke systems — every component is something a small team must understand and operate for years.

## 1.2 Why stable beats trendy

The single most important meta-principle: **prefer proven technology over trendy technology, except where a new technology offers a genuinely decisive, durable advantage.** The reasoning:

- **Trendy technology externalizes its risk onto you.** The newest framework or model has undiscovered failure modes, thin documentation, a small hiring pool, and an uncertain future. You become the unpaid QA team and the abandonment risk is real. Mature technology has had its risk paid down by everyone who came before you.
- **A startup's scarcest resource is engineering attention, and novelty is an attention tax.** Every hour spent fighting an immature tool's rough edges is an hour not spent on the product's actual differentiation (the AI editing quality). Boring infrastructure frees attention for the parts that matter.
- **The differentiation of Olympus is the *editing intelligence*, not the database or the web framework.** We want our innovation budget spent entirely on the unique, hard parts (the AI pipeline, the craft) and *zero* of it spent on reinventing solved infrastructure. So: be radically conservative on infrastructure, and concentrate novelty only where it is the product.
- **Stable technology compounds; trendy technology resets.** A mature stack lets the team accumulate deep expertise and reusable patterns over years. Chasing trends resets that expertise repeatedly. The team that masters a boring stack out-ships the team perpetually learning a new one.
- **The exception is real but narrow.** AI models are the one area where the frontier genuinely moves fast and where a newer model can be decisively better — so there, we adopt aggressively *but behind interfaces* (Part 2), treating models as replaceable commodities precisely because they change fast. Everywhere else, we are boring on purpose.

## 1.3 The resulting posture
Conservative, proven infrastructure (databases, queues, web stack) chosen for decades-long stability; aggressively current but *fully abstracted* AI models chosen for quality and swapped freely as the frontier moves; managed services adopted where they buy reliability and speed, always behind a replaceable interface; and a deliberately small number of languages and systems so a small team can own the whole thing for years. Boring where boring wins; cutting-edge only where it is the product; replaceable everywhere.

---

# Part 2 — AI Model Strategy

## 2.1 The meta-strategy: models are replaceable commodities behind stable interfaces

The frontier of AI models moves monthly; therefore the *worst* possible decision is to couple Olympus tightly to any one model. The strategy, inherited from the architecture's AI-contract seams (Phase 3A Part 8): **every AI capability sits behind a stable internal interface (a data contract), so any model — cloud or local, this vendor or that, this version or the next — can be swapped without touching the rest of the system.** We choose the best model *for each capability today*, and we design so that "best today" can become "best next quarter" with a configuration change, not a rewrite.

A second meta-principle: **buy (cloud API) for the MVP where it buys reliability and speed; build toward self-hosting (local/open models) where volume makes cost dominate.** Early on, managed model APIs eliminate operational burden and give state-of-the-art quality immediately; as volume grows, the highest-volume, most cost-sensitive capabilities (transcription especially) migrate to self-hosted open models on our own GPUs. The interface makes this migration invisible to the rest of the system.

## 2.2 Capability-by-capability recommendations

For each: purpose, requirements, accuracy needs, latency tolerance, cost sensitivity, and deployment recommendation.

### Speech-to-text (transcription)
- **Purpose:** produce the accurate, word-level timestamped transcript that is the backbone of all timing and understanding.
- **Best category:** a state-of-the-art **automatic speech recognition (ASR) model with word-level timestamps** — the Whisper family (e.g., `whisper-large-v3`) is the open-model gold standard; managed ASR APIs (Deepgram, AssemblyAI) offer comparable accuracy plus built-in diarization and robust timestamps.
- **Requirements:** word-level timing, segment boundaries, noise robustness, accent robustness, long-audio handling.
- **Accuracy needs:** **very high** — errors here propagate into captions and understanding. This is one of the two or three most accuracy-critical capabilities.
- **Latency tolerance:** **medium** — it's batch/background (minutes acceptable), not interactive.
- **Cost sensitivity:** **high** — transcription runs on every minute of every video; it is a top-three cost driver and the prime candidate for self-hosting.
- **Deployment:** **Hybrid, evolving.** MVP: a managed ASR API (Deepgram or AssemblyAI) for reliability, great timestamps, and free diarization. At volume: self-host `faster-whisper` (an optimized Whisper runtime) on our own GPUs, with alignment (e.g., WhisperX-style forced alignment) for precise word timing — a large cost saving. The interface makes the switch a config change.

### Language reasoning (the general reasoning engine)
- **Purpose:** the general-purpose reasoning that powers story understanding, selection, caption refinement, and editing rationale.
- **Best category:** a **frontier large language model via API** (GPT-4-class / Claude-class) for the MVP; open-weight models (Llama-class, Qwen-class) self-hosted for cost as volume grows and as open models close the gap.
- **Requirements:** strong reasoning, instruction-following, structured (schema-constrained) output, long-context handling (a full transcript).
- **Accuracy needs:** **high** — reasoning quality directly shapes Short quality, but it is checked by gates and is less unforgiving than ASR (a mediocre selection is recoverable; a wrong transcript is not).
- **Latency tolerance:** **medium** — background; a few seconds-to-minutes per call is fine.
- **Cost sensitivity:** **medium-high** — manageable by calling it judiciously (once per video for understanding, reused across Shorts) rather than per-frame.
- **Deployment:** **Cloud (API) for MVP; hybrid later.** Start with a frontier API for best quality and zero ops; abstract it so we can route specific tasks to cheaper/smaller or self-hosted open models as economics and open-model quality evolve.

### Story understanding
- **Purpose:** comprehend the transcript's meaning, find complete standalone moments, map setup→payoff/context dependencies (the Story Understanding System, MVP-thin).
- **Best category:** the **frontier reasoning LLM (above), prompted/structured for narrative analysis**, operating on the transcript (plus light audio/emotion cues). Not a separate model in the MVP — it is the reasoning engine applied to a specific, well-structured task with schema-constrained output.
- **Requirements:** long-context comprehension, reliable structured output (moments, roles, dependencies, confidence), honest uncertainty.
- **Accuracy needs:** **high** (the product's intelligence) — but gated and human-reviewable.
- **Latency tolerance:** **medium** (background, once per video).
- **Cost sensitivity:** **medium** (once per video, reused across Shorts).
- **Deployment:** **Cloud (API) for MVP**, same engine and migration path as Language Reasoning.

### Viral moment detection
- **Purpose:** assess share-triggering value of moments (Virality System) — *deferred as a live subsystem in the MVP* (Phase 3A Part 14), but the lightweight version is part of selection.
- **Best category:** the **reasoning LLM applied to the transcript/understanding**, prompted for the share-trigger signals (surprise, relatability, humor, etc.) — not a bespoke model in the MVP.
- **Requirements/accuracy:** medium; advisory, gated, identity-bounded.
- **Latency/cost:** low priority and low frequency in MVP.
- **Deployment:** **Cloud (API), folded into the reasoning calls**; becomes a richer dedicated capability in V2.

### Caption generation
- **Purpose:** turn transcript spans into accurate, well-timed, emphasis-aware caption data (Caption Intelligence).
- **Best category:** **primarily deterministic logic over the ASR word timestamps** (the timing comes from ASR, not a model), with the **reasoning LLM** used for emphasis selection, light cleanup, and segmentation into glanceable chunks. Captions are mostly a *data-shaping* problem, not a generation problem — the words and times already exist.
- **Requirements:** exact timing alignment, legibility, emphasis on the meaning-carrying word, no over-captioning.
- **Accuracy needs:** **very high on timing** (driven by ASR quality), high on emphasis.
- **Latency tolerance:** **medium**.
- **Cost sensitivity:** **low** (cheap once ASR exists).
- **Deployment:** **Local/deterministic + light cloud LLM** for emphasis/cleanup.

### Vision understanding (general scene/visual comprehension)
- **Purpose:** understand what's on screen to inform reframing, zoom, and (later) visual selection.
- **Best category:** for the MVP, **targeted classical/specialized CV** (below: scene, face, object, OCR) rather than a heavy general vision-language model; a VLM is a V2 enrichment.
- **Requirements:** locate subjects/faces and salient regions for subject-aware vertical reframing.
- **Accuracy/latency/cost:** medium accuracy; medium latency (background, sampled frames not every frame); cost-sensitive (frame analysis adds up) → **sample frames, don't analyze every frame**.
- **Deployment:** **Local** (runs on our GPU/CPU workers near the media) — cheaper and faster than shipping frames to a cloud API.

### Scene analysis (shot/scene boundary detection)
- **Purpose:** detect cuts/scene changes to respect natural boundaries when trimming and reframing.
- **Best category:** **classical, deterministic shot-detection** (e.g., PySceneDetect) — fast, reliable, cheap, no model needed.
- **Accuracy:** high enough; **latency:** fast; **cost:** negligible.
- **Deployment:** **Local.** A boring, proven library is exactly right here.

### Face detection
- **Purpose:** locate faces to keep subjects framed during vertical reframing and zooms (the cinematography of Phase 2's Camera language).
- **Best category:** a fast, accurate **face detector** (e.g., RetinaFace, or MediaPipe / a YOLO-face variant for speed).
- **Accuracy needs:** high (a missed face → decapitated crop, a top failure mode); **latency:** medium (sampled frames + tracking between samples); **cost:** local-cheap.
- **Deployment:** **Local**, on the processing workers.

### Object detection
- **Purpose:** identify salient non-face subjects for reframing/emphasis when no face dominates.
- **Best category:** a mature real-time **object detector** (YOLO family).
- **Accuracy/latency/cost:** medium accuracy; sampled frames; local-cheap.
- **Deployment:** **Local.** Used as a secondary subject cue after faces.

### OCR (on-screen text)
- **Purpose:** detect existing on-screen text (so captions don't collide with it; future: understanding burned-in text).
- **Best category:** a strong open OCR engine (PaddleOCR; Tesseract as a simpler baseline) or a cloud Vision OCR for hard cases.
- **Accuracy:** medium for MVP (collision-avoidance use); **latency:** medium (sampled); **cost:** local-cheap.
- **Deployment:** **Local** for MVP; cloud Vision optional for difficult content later.

### Speaker diarization
- **Purpose:** know *who* is speaking and *when* (for multi-speaker videos, framing the active speaker, attributing captions).
- **Best category:** a dedicated **diarization model** (pyannote.audio) — or, conveniently, the diarization built into managed ASR (Deepgram/AssemblyAI), which is why the managed-ASR MVP choice is attractive.
- **Accuracy needs:** medium-high (errors cause wrong active-speaker framing); **latency:** medium (background); **cost:** medium.
- **Deployment:** **Cloud (bundled with managed ASR) for MVP**; **local pyannote** when self-hosting ASR.

### Audio enhancement
- **Purpose:** voice clarity (denoise), consistent comfortable loudness, intelligibility (Audio Intelligence floor).
- **Best category:** a combination — **deterministic loudness normalization** (FFmpeg EBU R128 `loudnorm`) for levels, a **speech-denoise/enhancement model** (RNNoise for light real-time denoise; a learned speech-enhancement model or source separation like Demucs for harder cases) for clarity. Responsible, conservative (the Constitution's restraint) — never over-processed.
- **Accuracy/latency/cost:** loudness is deterministic and free; denoise is medium cost; **latency:** medium (background).
- **Deployment:** **Local** (FFmpeg + a local enhancement model on workers).

### Music recommendation (future)
- **Purpose:** suggest mood-matched, *rights-cleared* music beds (Audio Intelligence) — **deferred to V2** (Phase 3A Part 14).
- **Best category (future):** metadata/embedding-based matching over a *licensed* music library (match emotional tags/embeddings of the Short to library tracks) — *not* music generation in the near term, and never uncleared tracks.
- **Deployment (future):** cloud or local matching over a licensed catalog; clearance is the hard part, not the model.

### Thumbnail analysis (future)
- **Purpose:** assess/generate thumbnail frames (Publishing) — **deferred** (Phase 3A Part 14).
- **Best category (future):** a vision-language model to score frame appeal/clarity, plus face/emotion cues.
- **Deployment (future):** cloud VLM, low frequency.

## 2.3 The strategy summarized
Use **managed cloud APIs for the heavy "intelligence" capabilities in the MVP** (ASR with diarization, frontier LLM for understanding/selection/captions-emphasis) to get state-of-the-art quality with zero model-ops; use **fast, proven, local classical CV and deterministic audio tools** for the high-frequency media analysis (scene/face/object/OCR/loudness) because they're cheap, fast, and reliable near the media; and **abstract every model behind its contract** so that as volume grows we migrate the cost-dominant capabilities (transcription first, then LLM reasoning) to self-hosted open models on our own GPUs — invisibly to the rest of Olympus. Models are commodities; the interfaces are the asset.

---


# Part 3 — Video Processing Stack

## 3.1 The anchor: FFmpeg is the workhorse, and that is a deliberate choice

The single most important video-stack decision: **FFmpeg is the core media engine for virtually all deterministic media operations.** This is the textbook example of "boring beats trendy" — FFmpeg is two decades mature, ubiquitous, exhaustively documented, battle-tested at planetary scale, supports essentially every codec and container, and has a vast community. Building or adopting anything else for core media transforms would be reinventing the most proven wheel in the industry. Olympus's media layer is FFmpeg-centric by design.

## 3.2 Capability-by-capability

- **Decoding video:** **FFmpeg** (libavcodec). Handles every realistic input format from YouTube or uploads. *Why:* universal codec support and reliability — the input is unpredictable, and FFmpeg handles the long tail.
- **Trimming (cutting to the moment):** **FFmpeg.** Precise, keyframe-aware trimming. *Why:* exact, fast, lossless where possible (stream copy) or re-encoded when frame-accuracy demands it.
- **Transcoding:** **FFmpeg** with **H.264** as the MVP delivery codec (universal compatibility) and consideration of H.265/AV1 later for efficiency. *Why:* H.264 plays everywhere creators publish; efficiency codecs are a later cost optimization.
- **Resizing / vertical reframing:** **FFmpeg** for the mechanical crop/scale/pad to 9:16, driven by the *subject-aware crop path* computed by the CV layer (Part 2: face/object detection + tracking). *Why:* FFmpeg does the pixels; the intelligence about *where* to crop comes from the AI layer — the architecture's decide-vs-do split.
- **Frame extraction:** **FFmpeg** to sample frames for CV analysis (scene/face/object/OCR). *Why:* we sample frames (not every frame) for analysis to control cost; FFmpeg extracts them efficiently.
- **Subtitle / caption burning:** **FFmpeg + libass with ASS-format subtitles.** ASS supports styling, positioning, per-word timing, and basic karaoke-style highlight effects — enough for clean, emphasis-aware, *lightly animated* captions in the MVP. *Why:* it's reliable, GPU-free, and produces the premium caption look the MVP needs without a heavy compositor.
- **Caption animation (richer motion):** **MVP: libass/ASS** (word-highlight, fades, positioning). **V2: a programmatic compositor** — a headless renderer such as **Remotion** (React-driven video) or a frame-compositing pipeline — for true motion-graphics captions. *Why:* MVP gets 90% of the perceived quality from ASS cheaply; full kinetic typography is deferred (Phase 3A Part 14) to a dedicated compositor behind the same "caption plan" contract.
- **Audio extraction:** **FFmpeg** to pull a clean, transcription-ready audio stream. *Why:* trivial, reliable, universal.
- **Audio mixing:** **FFmpeg** filtergraphs for mixing voice, (future) music beds, and effects, with ducking. *Why:* FFmpeg's audio filters cover MVP needs; advanced sound design is V2.
- **Color / visual enhancement:** **FFmpeg filters** for *light, responsible* correction (exposure/white-balance/contrast within conservative bounds, loudness's visual analogue) for the MVP; a dedicated grading pipeline or learned enhancement model is V2. *Why:* the Visual Language Bible mandates restraint — light correction via proven filters is exactly right, and avoids the artifacts of aggressive enhancement.
- **Rendering (final composite + encode):** **FFmpeg** as the compositor/encoder for the MVP, executing the complete edit plan (trim + crop + zoom + burned captions + audio cleanup + light grade) in as few passes as possible. *Why:* one proven engine for the whole render keeps the rendering layer simple and reliable; a richer compositor (Remotion/NLE-style) arrives with motion graphics in V2.
- **Hardware acceleration:** **NVENC/NVDEC** (NVIDIA GPU encode/decode) on GPU render workers, with CPU (libx264) as the portable fallback. *Why:* GPU encode dramatically cuts render time and cost-per-render at volume; CPU fallback keeps us portable and handles cases where GPU isn't available. FFmpeg supports both behind the same interface.

## 3.3 Why this stack fits Olympus
It is **one proven engine (FFmpeg) for the deterministic media work**, fed by a **separate intelligence layer** that decides *what* to do — exactly the architecture's decide/do separation. It is cheap, reliable, universally compatible, and hardware-acceleratable. It deliberately uses the *lightest* tool that achieves the premium-feeling MVP result (ASS captions, FFmpeg filters) and defers heavier compositors to V2 behind stable contracts. The risk (FFmpeg's complexity and operational quirks) is mitigated by its maturity and documentation, and by isolating it inside the well-defined Rendering/Processing workers so its complexity doesn't leak into the rest of the system.

---

# Part 4 — Backend Technology

## 4.1 Language strategy: two languages, chosen deliberately

**Python for the backend (API + workers + AI/video), TypeScript for the frontend.** This is a deliberate, conservative two-language choice:
- **Python** because the entire AI and video ecosystem (model runtimes, FFmpeg bindings, CV libraries, ML tooling) is Python-native — using anything else for the workers would mean fighting the ecosystem. Putting the API in Python too means the API and workers *share one language and codebase*, which is a huge maintainability win for a small team (shared domain models, shared types, one toolchain).
- **TypeScript** for the frontend (and any edge/realtime needs) because it is the proven, type-safe standard for modern web UIs.
- *Why not one language everywhere?* A single language (e.g., all TypeScript) would fight the Python-dominant AI/video ecosystem; a more exotic single language (Go/Rust everywhere) would sacrifice the AI ecosystem and the hiring pool. Two well-chosen languages, each dominant in its domain, is the pragmatic optimum.

## 4.2 The components

- **API server:** **FastAPI (Python).** *Why:* async-native (right for an I/O-bound edge that mostly enqueues work and reads state), excellent developer experience, automatic OpenAPI schema (which feeds the typed frontend client), strong validation (Pydantic), mature and widely adopted. *Alternatives:* Node/NestJS (would split languages from the workers — rejected for maintainability); Django (heavier, less async-natural for this thin edge). *Trade-off:* Python's raw throughput is lower than Go/Node, but the edge is thin and I/O-bound, so this is a non-issue, and the shared-language win dominates.
- **Asynchronous workers:** **Python workers** running the pipeline stages. *Why:* same language as API and AI/video code; shares domain models and the AI contracts directly. *Trade-off:* Python's concurrency model (GIL) is weak for CPU-bound work — mitigated because the heavy lifting happens in FFmpeg/native model runtimes (which release the GIL or run as subprocesses), and we scale by *process/worker count*, not threads.
- **Job queue:** **Celery with Redis as broker** for the MVP; **RabbitMQ** (or Redis Streams) as the upgrade for stronger delivery guarantees at scale. *Why Celery+Redis:* the most proven, well-documented task-queue pattern in the Python world; fast to stand up; good-enough durability for the MVP with idempotent jobs. *Alternatives:* RabbitMQ (more robust routing/durability — the V2 target); cloud-native queues (SQS) for managed durability; newer task frameworks (rejected for MVP as less proven). *Trade-off:* Redis-as-broker is less durable than RabbitMQ/SQS; mitigated by idempotent, resumable jobs (architecture Part 9) and by keeping authoritative state in Postgres, not the broker.
- **Caching:** **Redis.** *Why:* the proven default for caching, ephemeral state, rate-limit counters, and (doubling as) the Celery broker in MVP. One mature system covering several needs reduces operational surface.
- **Authentication:** **A managed auth provider for the MVP** (e.g., Clerk/Auth0-class), behind our own Auth-service interface; **self-hosted auth** (a proven library + Postgres) as the cost/control upgrade. *Why managed first:* auth is security-critical and easy to get subtly wrong; a managed provider gives secure, complete auth (sessions, refresh, MFA, recovery) immediately. *Trade-off:* per-user cost and a vendor dependency — mitigated by hiding it behind our Auth interface so we can self-host later without touching callers.
- **Configuration management:** **Environment-based config + a secrets manager** (cloud-native secrets service); config-as-data, never secrets in code. *Why:* the boring, standard, secure approach; environment parity (architecture Part 10) falls out naturally.
- **Logging:** **Structured (JSON) logging** with correlation ids, shipped to a centralized log store/observability platform (e.g., an ELK/OpenSearch stack self-hosted, or a managed platform like Datadog/Grafana Loki for MVP speed). *Why:* structured + correlated logs are required for per-job traceability (the blueprint's inspectability); managed first to avoid running a logging cluster early.
- **Monitoring:** **Metrics + alerting** via the Prometheus/Grafana ecosystem (or a managed equivalent for MVP), tracking the architecture's signals (queue depth, worker health, success/failure rates, render times). *Why:* the proven open standard for metrics; managed option trades cost for zero-ops early.
- **Analytics:** **A privacy-respecting product-analytics tool** (self-hostable like PostHog, or a managed equivalent) plus aggregates in Postgres. *Why:* PostHog is open, self-hostable (data ownership), and covers MVP product analytics without building bespoke pipelines.
- **Notifications:** **A transactional email/notification provider** (e.g., a reputable email API) behind our Notifications interface, plus in-app notifications via the API. *Why:* deliverability is a specialized problem best bought; the interface keeps the provider replaceable.

## 4.3 The backend posture
Conservative, proven, Python-centric, with managed services bought for the security- and ops-heavy concerns (auth, logging, monitoring, email) *behind interfaces*, and the core (FastAPI + Celery + Redis + Postgres) being the most boring, well-trodden Python production stack in existence. Maximum proven-ness, minimum moving parts, one backend language, every external dependency replaceable.

---

# Part 5 — Database Strategy

## 5.1 Primary database: PostgreSQL

**PostgreSQL is the primary database, unambiguously.** *Why:* it is the most capable, reliable, and respected open relational database in the world — mature, ACID-compliant, exhaustively documented, with a massive community and hiring pool. It comfortably handles all of Olympus's relational state (users, projects, videos, transcripts metadata, clips, exports, jobs, preferences, analytics), and it has powerful extras that *defer* the need for other systems: rich JSON support (for semi-structured plan/understanding summaries), full-text search (defers a search engine), and strong indexing. *Alternatives considered:* MySQL (capable, but Postgres's feature set and JSON/search support are stronger for us); a NoSQL document store (rejected — our data is highly relational and state-driven, exactly Postgres's strength; NoSQL would trade away the integrity and query power we need). *Scaling path:* vertical scaling first (it goes far), then read replicas for read-heavy load, then partitioning of the largest tables (jobs/logs) — a well-understood path we won't outgrow for a long time.

## 5.2 Caching layer: Redis

**Redis**, as in Part 4. *Why:* the proven in-memory store for caching hot reads, ephemeral state, rate-limit counters, and progress data, plus the MVP queue broker. *Scaling path:* managed Redis with replicas/clustering as needed. One mature system, several jobs.

## 5.3 Search / indexing

**MVP: PostgreSQL full-text search.** *Why:* the MVP's search needs are modest (a creator finding their projects); Postgres FTS handles this with *zero* additional infrastructure. **V2/V3: a dedicated search engine** (OpenSearch/Elasticsearch) *only if and when* search needs grow (searching transcripts across many videos, advanced filtering). *Why defer:* adding a search cluster early is operational burden for a need we don't yet have — a textbook "don't add a system until the data forces you to."

## 5.4 Object storage

**S3-compatible object storage** for all media artifacts (architecture Part 7) — **AWS S3** as the reference, with **strong consideration of Cloudflare R2 or Backblaze B2** specifically to avoid **egress fees**, which are a major hidden cost for a video product serving large files. *Why:* object storage is the correct, elastic, durable home for large binaries; S3-compatibility is a near-universal standard, so the *provider* is replaceable behind the same interface. *Why R2/B2 consideration:* serving video means heavy egress; zero/low-egress providers can dramatically cut bandwidth cost (Part 10). *Scaling path:* object storage is effectively infinitely scalable; the decision is purely cost/egress optimization, made behind a standard S3 interface.

## 5.5 Backup strategy

- **PostgreSQL:** automated daily backups **plus** point-in-time recovery (continuous WAL archiving), tested restores (an untested backup is not a backup), and retention appropriate to recovery needs. *Why:* the Database is the source of truth; losing it loses the product's state.
- **Object storage:** durability is provided by the storage service's own replication; additionally, **versioning** on critical buckets (masters, exports) and **lifecycle policies** (architecture Part 7) to prevent accidental loss and control growth. Cross-region replication for the most critical artifacts is a V2 consideration.
- **Disaster recovery:** a documented, periodically-rehearsed recovery procedure (architecture Part 10.7). *Why:* creators' uploaded work and outputs must survive infrastructure failure.

## 5.6 The database posture
One boring, world-class relational database (Postgres) as the source of truth, doing more than people expect (JSON, FTS) so we add *fewer* other systems; Redis for caching/ephemeral; S3-compatible object storage for bytes with egress-cost awareness; search deferred until data demands it; backups automated, point-in-time, and *tested.* Maximum reliability, minimum systems, clear scaling path, every storage choice behind a standard interface.

---


# Part 6 — Frontend Technology

## 6.1 The anchor: a proven, type-safe React stack, kept deliberately thin

The frontend is a thin presentation client (architecture Part 5), so the technology choice optimizes for *developer velocity, type safety, and a fast, simple interface* — not for frontend sophistication. The stack:

- **Web frontend framework:** **React with Next.js, in TypeScript.** *Why:* React is the most proven, best-supported UI ecosystem with the largest hiring pool; Next.js adds production-grade routing, rendering, and a strong developer experience; TypeScript gives end-to-end type safety (and pairs with FastAPI's OpenAPI schema to generate a typed API client, eliminating a whole class of bugs). *Alternatives:* a lighter SPA (less batteries-included); other frameworks (smaller ecosystems/hiring pools). *Trade-off:* Next.js is more than a tiny app strictly needs, but its maturity, ecosystem, and the typed-client win justify it, and it scales with us.
- **State management:** **TanStack Query (server-state) + a minimal client-state store (e.g., Zustand).** *Why:* the crucial insight is that *most* of Olympus's frontend state is *server state* (projects, jobs, results, progress) — TanStack Query handles fetching, caching, polling, and synchronization of server state beautifully, which is exactly the progress-tracking and results-fetching the product needs. A heavy global-state library (Redux) is unnecessary; a tiny store covers the little genuine client state (UI toggles, form drafts). *Trade-off:* none significant — this is the modern, lean, correct pattern for a server-state-heavy app.
- **UI components:** **Tailwind CSS + a headless/component library (Radix primitives, e.g., via shadcn/ui).** *Why:* Tailwind gives fast, consistent, maintainable styling; Radix/shadcn gives accessible, unstyled-but-correct component primitives we style to Olympus's identity — accessibility (the Visual Language Bible's floor) comes built-in. *Alternatives:* a heavy opinionated component kit (harder to make feel premium/custom). *Trade-off:* slightly more assembly than an all-in-one kit, in exchange for a custom premium look and accessibility correctness.
- **Upload experience:** **Direct-to-storage uploads via scoped, time-limited presigned URLs, with resumable/multipart upload** (the architecture's "large bytes never go through the API" rule; a resumable protocol like tus or S3 multipart for large files). *Why:* videos are large; uploading directly to object storage (not through the API) is faster, cheaper, and more reliable, and resumability handles flaky connections. *Trade-off:* slightly more client complexity, fully justified for large-file reliability.
- **Progress tracking:** **State-derived progress via TanStack Query polling for the MVP; server-sent events (SSE) or websockets as a V2 refinement** for push updates. *Why:* polling the status resource is simple, reliable, and entirely sufficient for minutes-long jobs in the MVP; push (SSE/websockets) is a nice-to-have upgrade, not an MVP need. Progress is always *honest* and state-derived (architecture Part 5/9).
- **Video preview:** **The native HTML5 video element** for previewing finished Shorts (standard formats play natively), with **hls.js** only if adaptive streaming is later needed. *Why:* finished Shorts are standard H.264 files that play natively — no heavy player needed for the MVP.
- **Authentication flow:** **The managed auth provider's client SDK** (Part 4) integrated into the React app, behind a thin app-level auth wrapper. *Why:* secure, complete auth flows (sign-in, refresh, recovery, MFA) without building them; the wrapper keeps the provider replaceable.

## 6.2 Keeping the interface fast and simple
- **Thin client, server-state-first:** almost all logic is server-side; the frontend mostly *reflects* server state via TanStack Query, which keeps it simple and inherently consistent.
- **Minimal client state, minimal dependencies:** no heavy global-state machinery; few, proven libraries; small bundle.
- **Honest, calm UX over flashy UX:** the interface's job (architecture Part 5) is to make a long process feel trustworthy — clear states, honest progress, plain-language errors — not to be a heavy interactive app.
- **Accessibility and performance as defaults:** Radix accessibility, Tailwind's lean output, native video, and direct-to-storage uploads all serve a fast, inclusive, premium-feeling interface.

---

# Part 7 — Infrastructure & Deployment

## 7.1 Cloud architecture: one major cloud, standard primitives, cost-aware storage

**A single major cloud provider (AWS as the reference choice) for compute, networking, database, and orchestration, with object storage chosen for egress cost (S3, or R2/B2 for media to cut bandwidth — Part 5/10).** *Why one cloud:* a small team should not split focus across multiple clouds; one provider with mature managed services (managed Postgres, managed Redis, container hosting, secrets, GPU instances) minimizes operational burden. *Why standard primitives:* using boring, standard cloud services (not exotic ones) keeps us portable and hireable. *Cost-aware twist:* media/object storage and CDN are the exception where we deliberately consider a cheaper-egress provider, because video bandwidth is a dominant cost.

## 7.2 The components

- **GPU usage:** **Serverless / on-demand GPU for the MVP** (a platform like Modal, Replicate, or RunPod, or cloud GPU instances spun up per-batch) for transcription and GPU-accelerated rendering; **reserved/owned GPU capacity** only once utilization is high enough to justify it (V2+). *Why:* GPUs are expensive and *idle GPUs are pure waste*; serverless/on-demand GPU means we pay only for actual inference/render time during the MVP's spiky, low-volume usage. *Migration:* as steady volume grows, owned/reserved GPUs become cheaper per unit — a cost-driven switch behind the same worker interface.
- **CPU workers:** **Containerized CPU worker pools** for the light pipeline stages (download, audio extraction, scene/face/OCR sampling, light FFmpeg work, orchestration). *Why:* most stages are CPU-fine and cheap; reserve GPU strictly for what needs it.
- **Storage:** **S3-compatible object storage** (Part 5), with **lifecycle policies** (architecture Part 7) for cost control.
- **CDN:** **A CDN in front of media delivery** (CloudFront, or Cloudflare paired with R2 for low egress) so creators download/preview Shorts fast and cheaply. *Why:* serving video directly from origin is slow and expensive; a CDN is standard and essential for a video product.
- **Containerization:** **Docker** for all services/workers. *Why:* the universal standard; gives environment parity (architecture Part 10.2) and portability across providers. *Trade-off:* none meaningful — this is table stakes.
- **Orchestration:** **MVP: a managed container service** (e.g., a managed container/orchestration offering — ECS/Fargate-class, or a managed Kubernetes only if needed). **V2+: Kubernetes** if/when scale and complexity justify it. *Why:* full Kubernetes is operational overkill for the MVP and a notorious time-sink for small teams; a managed container service runs our containers with far less burden. *Migration:* containers are portable, so adopting Kubernetes later is an infrastructure change, not an app rewrite.
- **Deployment strategy:** **Conservative, reversible deploys** (rolling/blue-green) with the ability to roll back fast (architecture Part 10.7); nothing touching creators' real work ships without passing staging.
- **Scaling approach:** **Independent, queue-depth-driven autoscaling per worker type** (architecture Part 10.3) — render pool scales on render demand, transcription on its queue, etc.; the thin API scales horizontally on traffic. *Why:* the heavy/expensive layer scales on its own demand without over-provisioning the rest.
- **CI/CD:** **GitHub Actions** (or equivalent) for automated build, test, and deploy pipelines; **Infrastructure-as-Code (Terraform)** for reproducible, reviewable infrastructure. *Why:* GitHub Actions is the proven, low-friction CI/CD standard; Terraform makes infrastructure versioned, reviewable, and reproducible across environments — essential for environment parity and disaster recovery.

## 7.3 What to optimize for MVP vs. later
- **MVP optimizes for: operational simplicity and avoiding waste.** Managed services (container hosting, Postgres, Redis, GPU-on-demand) over self-run infrastructure; pay-per-use GPU over owned GPU; one cloud; managed observability. The goal is a small team running a reliable system with minimal ops, paying only for what's used during low/spiky volume.
- **Later (V2/V3) optimizes for: cost-per-unit at scale.** Owned/reserved GPUs, possibly self-hosted models (Part 2), possibly Kubernetes, possibly self-hosted observability — each adopted *only when volume makes the managed convenience more expensive than the operational burden of self-hosting.* Every such switch is behind an interface, so it's a cost optimization, not a redesign.

---

# Part 8 — Third-Party Services

## 8.1 Philosophy on dependencies
Buy what is not our differentiation and is hard to do well (auth, email deliverability, observability, frontier models); build/own what *is* our differentiation (the editing intelligence and pipeline). Every third-party service sits **behind our own interface** so it is replaceable, and we avoid services that would deeply lock us in.

## 8.2 Required (the MVP needs these)
- **Cloud provider (compute/DB/networking) + object storage + CDN.** *Useful:* the foundation; managed primitives let a small team operate reliably. *Risk:* the deepest dependency, with real switching cost. *Replacement:* mitigated by using *standard* primitives (containers, S3-compatible storage, managed Postgres) that exist on every cloud, so migration is possible if painful; IaC (Terraform) makes the infrastructure reproducible.
- **Managed ASR (speech-to-text) API** (Deepgram/AssemblyAI-class). *Useful:* state-of-the-art transcription + diarization + timestamps with zero model-ops — the MVP's accuracy backbone. *Risk:* per-minute cost (a top cost driver) and vendor dependency. *Replacement:* behind the Transcription contract (Part 2); self-hosted Whisper is the planned migration at volume.
- **Frontier LLM API** (for understanding/selection/caption-emphasis). *Useful:* best-in-class reasoning instantly. *Risk:* cost, rate limits, model-version drift, vendor dependency. *Replacement:* behind the reasoning contract; route to alternate/open models as they mature.
- **GPU compute platform** (serverless GPU for MVP). *Useful:* pay-per-use GPU avoids idle-cost waste. *Risk:* per-use cost, cold starts, vendor specifics. *Replacement:* behind the worker interface; move to owned GPUs at volume.
- **Transactional email/notification provider.** *Useful:* deliverability is specialized; bought, not built. *Risk:* low; replaceable. *Replacement:* behind the Notifications interface.

## 8.3 Optional (valuable for MVP, not strictly required)
- **Managed auth provider** (Clerk/Auth0-class). *Useful:* secure, complete auth fast. *Risk:* per-user cost, dependency. *Replacement:* behind the Auth interface; self-host later. (Borderline required for MVP speed; listed optional because a self-hosted auth library is a viable MVP path.)
- **Managed observability** (logging/metrics, Datadog/Grafana Cloud-class). *Useful:* full observability without running the stack. *Risk:* cost grows with volume. *Replacement:* open standards (OpenTelemetry, Prometheus) let us move to self-hosted (Grafana/OpenSearch) later.
- **Managed product analytics** (PostHog-class). *Useful:* product insight without building pipelines. *Risk:* low; self-hostable. *Replacement:* PostHog is open-source/self-hostable by design.
- **Error tracking** (Sentry-class). *Useful:* fast debugging of real failures. *Risk:* low. *Replacement:* open standards / self-hostable.

## 8.4 Future upgrades (V2+)
- **Licensed music catalog provider** (for music beds — clearance is the hard part, Part 2). *Risk:* licensing complexity; *strategy:* a reputable licensed-catalog partner, behind a music interface.
- **Advanced/dedicated CV or VLM APIs** (richer scene/thumbnail understanding) as those capabilities are added.
- **Direct publishing/scheduling integrations** (platform APIs) when publishing is built.
- **Self-hosted model infrastructure** (an inference-serving stack) as we migrate cost-dominant models in-house.

## 8.5 The dependency posture
A short list of *required* externals (cloud, ASR, LLM, GPU, email), each behind an interface and chosen on open standards where possible; *optional* managed services that buy speed/reliability now and are replaceable later (auth, observability, analytics, error tracking); and *future* services added as capabilities grow. The rule throughout: **depend on it only behind our own interface, prefer open standards, and never let a convenience become a cage.**

---


# Part 9 — Engineering Trade-offs

A consolidated decision record for the major choices. For each: selection, alternatives considered, advantages, disadvantages, and future migration path. The throughline is *engineering judgment over hype* — every choice is defensible on reliability/cost/maintainability grounds, and every one has an exit.

### Backend language — Python
- **Alternatives:** Node/TypeScript everywhere; Go; Rust.
- **Advantages:** native to the AI/video ecosystem; one language for API + workers + AI; huge hiring pool; fast development.
- **Disadvantages:** lower raw throughput and weak threaded concurrency (GIL).
- **Migration path:** the edge is I/O-bound (throughput a non-issue) and heavy work runs in native FFmpeg/model runtimes; if a specific hot path ever needs it, isolate that service and rewrite *only it* in Go/Rust behind its interface. The architecture's service boundaries make a targeted rewrite possible without a system rewrite.

### API framework — FastAPI
- **Alternatives:** Django, Flask, Node/NestJS.
- **Advantages:** async-native, great DX, auto OpenAPI (→ typed frontend client), strong validation, mature.
- **Disadvantages:** less batteries-included than Django (we add pieces deliberately).
- **Migration path:** the API is a thin edge behind a versioned contract (architecture Part 12); replacing the framework is bounded and contract-preserving.

### Job queue — Celery + Redis (MVP) → RabbitMQ/SQS (scale)
- **Alternatives:** RabbitMQ now; cloud SQS; newer task frameworks.
- **Advantages:** fastest proven path in Python; minimal new infrastructure (Redis already present).
- **Disadvantages:** Redis-as-broker is less durable than RabbitMQ/SQS; Celery has operational quirks at scale.
- **Migration path:** idempotent, resumable jobs + Postgres-as-truth mean we can swap the broker to RabbitMQ or a managed queue with low risk when durability/scale demands it.

### Primary database — PostgreSQL
- **Alternatives:** MySQL; a NoSQL document store; multiple specialized stores.
- **Advantages:** world-class reliability; relational integrity for state-heavy data; JSON + FTS defer other systems; massive ecosystem.
- **Disadvantages:** a single relational store needs deliberate scaling work eventually (replicas, partitioning).
- **Migration path:** vertical → read replicas → partition the largest tables; extract specialized stores (search) only when data forces it. A very long runway before any of this is needed.

### Object storage — S3-compatible (S3 / R2 / B2)
- **Alternatives:** storing media on disk/in DB (rejected outright); a single-cloud-only store.
- **Advantages:** elastic, durable, standard interface, replaceable provider; egress-optimized options cut bandwidth cost.
- **Disadvantages:** egress fees (mitigated by provider choice + CDN).
- **Migration path:** S3-compatibility means changing provider is a config/interface change, not a redesign.

### Media engine — FFmpeg (+ NVENC, libass)
- **Alternatives:** higher-level media SDKs; a custom compositor; Remotion for all rendering.
- **Advantages:** unmatched maturity, codec coverage, reliability, hardware accel; the industry workhorse.
- **Disadvantages:** complex API/operational quirks; static caption animation (mitigated with ASS now, compositor later).
- **Migration path:** isolated inside the Processing/Rendering workers; a richer compositor (Remotion) is added *alongside* for motion graphics in V2 behind the edit-plan contract, not as a replacement of core encode.

### AI models — managed cloud APIs (MVP) → self-hosted open models (scale)
- **Alternatives:** self-host from day one (premature ops burden); single-vendor lock-in (rejected).
- **Advantages:** SOTA quality instantly, zero model-ops, fast iteration.
- **Disadvantages:** per-use cost (a top cost driver), rate limits, version drift, vendor dependency.
- **Migration path:** every model behind a contract (Part 2); migrate cost-dominant capabilities (ASR first, then LLM) to self-hosted open models on owned GPUs — invisibly to the system.

### Frontend — React/Next.js/TypeScript + TanStack Query + Tailwind/Radix
- **Alternatives:** lighter SPA; other frameworks; heavy global-state libraries.
- **Advantages:** largest ecosystem/hiring pool; type safety end-to-end; server-state-first fits the product; accessibility built-in.
- **Disadvantages:** Next.js is somewhat more than a tiny app needs.
- **Migration path:** the frontend is a thin client behind the API contract; even a full frontend rewrite wouldn't touch the backend.

### Orchestration — managed containers (MVP) → Kubernetes (scale)
- **Alternatives:** Kubernetes from day one; bare VMs.
- **Advantages:** containers give portability/parity; managed hosting minimizes ops for a small team.
- **Disadvantages:** managed services are less flexible than raw K8s.
- **Migration path:** containers are portable; adopting K8s later is an infra change, not an app change.

### Auth / observability / email / analytics — managed (MVP) → self-host (later, where cost justifies)
- **Alternatives:** build/self-host from day one.
- **Advantages:** security/deliverability/observability done right, instantly, with little ops.
- **Disadvantages:** recurring cost, vendor dependency.
- **Migration path:** all behind interfaces and on open standards (OpenTelemetry, self-hostable PostHog/auth libs), so each can be self-hosted when volume tips the economics.

### The trade-off philosophy
Every "MVP" choice that leans on a managed service or a simpler tool is paired with a *named, low-risk migration path* enabled by the architecture's interfaces. We never choose convenience without an exit, and we never choose novelty without a decisive reason. This is engineering judgment: optimize for reliability and speed now, preserve optionality always.

---

# Part 10 — Cost Strategy

## 10.1 Where the money goes (largest → smallest, typical for this product)

1. **AI inference (ASR + LLM).** Transcription runs on every minute of every video; LLM reasoning runs per video (and grows with usage). Together, the largest variable cost early. **The cost center to watch most closely.**
2. **Rendering (GPU compute).** Video encoding is compute-heavy; GPU render time per Short, times 3–5 Shorts per video, times volume. A top cost driver as usage scales.
3. **Bandwidth (egress).** Serving and previewing video is large-file delivery; egress fees can balloon and are easy to underestimate.
4. **Storage.** Source videos, masters, exports accumulate; large files at volume, controlled by lifecycle.
5. **GPUs (idle capacity).** If GPUs are owned/reserved before utilization justifies it, *idle GPU is pure waste* — a self-inflicted cost.
6. **Databases / managed services.** Real but typically smaller than the above for a video product; grows with managed-service usage.

## 10.2 How the MVP minimizes cost without sacrificing quality

- **Compute understanding once, reuse across Shorts** (architecture economics): ASR, transcript, and understanding run *once per video*; only the cheap per-Short stages repeat. This single design choice cuts the dominant AI cost dramatically.
- **Pay-per-use GPU, never idle GPU:** serverless/on-demand GPU for the MVP (Part 7) means we pay only for actual inference/render seconds during spiky low volume — eliminating the biggest avoidable waste.
- **Sample frames, don't analyze every frame:** CV analysis (face/object/scene/OCR) runs on sampled frames with tracking between, not every frame — a large saving with negligible quality loss.
- **Use local/deterministic tools for high-frequency work:** scene detection, loudness, face/object detection run locally and cheaply, reserving expensive cloud AI for the genuinely hard reasoning.
- **Egress-optimized storage + CDN:** choose a low-egress storage provider (R2/B2) and front media with a CDN, directly attacking the bandwidth cost; serve via cached CDN, not origin.
- **Aggressive lifecycle cleanup:** delete intermediates eagerly, retention-window sources/exports, keep only small valuable artifacts (masters/transcripts/plans) long-term (architecture Part 7) — controlling storage growth.
- **Right-size models per task:** use the smallest model that meets the accuracy bar for each capability (e.g., a cheaper LLM tier for simple tasks, the frontier model only where reasoning truly needs it); the model interface makes per-task routing easy.
- **H.264 + GPU encode:** efficient, universal delivery codec with hardware-accelerated encoding to minimize render time/cost; efficiency codecs (H.265/AV1) considered later as a bandwidth optimization.
- **Quality is never the thing cut:** crucially (the Constitution), cost is minimized through *efficiency* (reuse, sampling, right-sizing, lifecycle, egress), **never** by lowering the quality floor (no skipping gates, no degrading output to save compute). We cut waste, not quality.

## 10.3 The cost posture
Attack the top three (AI inference, rendering, bandwidth) with *architecture-level* savings (compute-once-reuse-many, pay-per-use GPU, frame sampling, egress-optimized delivery, lifecycle cleanup) rather than quality cuts. The MVP's spiky low volume is exactly suited to pay-per-use everything; as volume grows and per-use becomes expensive, migrate the cost-dominant pieces (self-hosted ASR, owned GPUs, efficiency codecs) behind their interfaces. Spend on quality where the creator feels it; cut waste everywhere they don't.

---

# Part 11 — Risk Assessment

The biggest technical risks, each with impact, likelihood, and mitigation.

### 1. AI model changes / drift (vendor model updated, deprecated, or behavior shifts)
- **Impact:** high — output quality could change unexpectedly; a deprecated model could break a capability.
- **Likelihood:** high — frontier models change frequently.
- **Mitigation:** every model behind a stable contract (Part 2); pin versions where the vendor allows; evaluate new versions in staging against a regression set *before* adopting; maintain the ability to route to an alternate model. Model drift is expected and absorbed by design.

### 2. Vendor lock-in (cloud, ASR, LLM, auth)
- **Impact:** high — deep coupling could trap us in rising prices or a failing vendor.
- **Likelihood:** medium.
- **Mitigation:** depend on every vendor *only behind our interface*; prefer open standards (S3-compatible storage, OpenTelemetry, containers, OpenAPI); maintain named migration paths (Part 9). Lock-in is actively designed against.

### 3. Rendering bottleneck (render is slow/expensive; a backlog forms)
- **Impact:** high — slow time-to-result hurts the core promise; render is a top cost.
- **Likelihood:** medium-high as volume grows.
- **Mitigation:** GPU-accelerated encode (NVENC); isolated, independently-autoscaled render pool (architecture Part 10); per-Short parallelism; pay-per-use GPU scaling on queue depth; efficiency-codec option later. Render is the most watched performance/cost surface.

### 4. Queue congestion (work backs up under load spikes)
- **Impact:** medium-high — delayed results, poor experience.
- **Likelihood:** medium.
- **Mitigation:** durable queues with backpressure (work queues, not drops); autoscaling workers on queue depth; priority/fairness so one big job can't starve others; monitoring on queue depth with alerts (architecture Part 9/10).

### 5. Storage growth (media accumulates, cost balloons)
- **Impact:** medium — rising storage cost over time.
- **Likelihood:** high (without discipline).
- **Mitigation:** the lifecycle/cleaning strategy (architecture Part 7) — eager intermediate cleanup, retention windows, orphan sweeps, account-deletion completeness; egress-optimized provider. Storage growth is controlled by policy from day one.

### 6. API limits / rate limits (managed AI APIs throttle us)
- **Impact:** medium-high — throttling stalls the pipeline.
- **Likelihood:** medium.
- **Mitigation:** request appropriate quotas; backoff-and-retry on rate limits (architecture Part 9); queue absorbs throttling without dropping work; multi-provider capability behind the model interface as a fallback; self-hosting removes the limit entirely at volume.

### 7. Scaling challenges (a component doesn't scale as hoped)
- **Impact:** medium — growth friction.
- **Likelihood:** medium.
- **Mitigation:** every layer chosen with a *known* scaling path (Parts 4–7); independent per-layer autoscaling; the Database's replica/partition path; load-testing the heavy paths in staging (architecture Part 10.2) so scaling limits are found before production.

### 8. Cost overrun (variable costs grow faster than revenue)
- **Impact:** high — existential for a startup.
- **Likelihood:** medium.
- **Mitigation:** the full cost strategy (Part 10) — compute-once-reuse, pay-per-use GPU, sampling, egress optimization, lifecycle, right-sized models; cost monitoring/alerting; per-account quotas (security/abuse, architecture Part 13). Cost is actively engineered, not hoped about.

### 9. FFmpeg/media edge cases (a weird input breaks processing)
- **Impact:** medium — individual job failures.
- **Likelihood:** medium-high (inputs are unpredictable).
- **Mitigation:** FFmpeg's maturity handles most; validate inputs early (architecture Part 13); fail individual jobs loudly and specifically with per-Short isolation; sandbox media processing; build a regression set of nasty inputs.

### 10. Transcription accuracy on hard audio (noise, accents, overlap)
- **Impact:** medium-high — bad transcript poisons captions and understanding.
- **Likelihood:** medium.
- **Mitigation:** strong managed ASR with confidence flags; the Understanding Gate catches low-confidence and can escalate to the creator rather than building on a bad transcript (architecture Part 3).

### Risk posture
The recurring mitigation is the architecture itself — interfaces (anti-lock-in, model-drift absorption), durable queues + idempotency (congestion/failure), isolated autoscaled pools (render/scale), lifecycle policy (storage), and gates (accuracy). Risk is managed structurally, by the design, not by hoping nothing goes wrong.

---


# Part 12 — Technology Roadmap

How the stack evolves across stages, and what stays stable vs. what gets replaced.

## 12.1 MVP
- **Compute/intelligence:** managed ASR API, frontier LLM API, local classical CV, deterministic audio (FFmpeg loudnorm + light denoise), serverless/on-demand GPU.
- **Media:** FFmpeg core, libass/ASS captions, NVENC where available, H.264 delivery.
- **Backend:** Python + FastAPI, Celery + Redis, PostgreSQL, S3-compatible storage, Redis cache.
- **Frontend:** React/Next.js/TypeScript, TanStack Query, Tailwind/Radix, direct-to-storage uploads, polling progress.
- **Infra:** one cloud, managed containers, managed Postgres/Redis, CDN, GitHub Actions + Terraform, managed observability/auth/email.
- **Goal:** reliable spine, premium-feeling output, minimal ops, pay-per-use everything.

## 12.2 V2
- **Intelligence:** begin **self-hosting ASR** (faster-whisper on owned/reserved GPU) — the first cost migration; introduce richer CV (subject tracking, VLM enrichment); add the deferred intelligence (branching/multi-version, deeper personalization seeded from Creator Preferences, the start of virality/Internet-Intelligence modules).
- **Media:** add a **programmatic compositor (Remotion or equivalent)** for motion-graphics captions and richer treatments, behind the edit-plan contract; consider H.265/AV1 for bandwidth.
- **Backend:** **RabbitMQ or managed queue** replacing Redis-broker for stronger durability; possibly **read replicas** on Postgres; SSE/websocket push for progress.
- **Infra:** **owned/reserved GPUs** as utilization justifies; possibly **Kubernetes** if scale/complexity demands; begin self-hosting observability if cost justifies.
- **Goal:** richer craft, deeper intelligence, first cost-at-scale migrations — all behind existing interfaces.

## 12.3 V3
- **Intelligence:** **self-hosted open LLMs** for cost-dominant reasoning tasks (routing the rest to APIs); full cognitive/branch/version machinery; full virality + Internet Intelligence Network; music/localization/thumbnail capabilities.
- **Media:** advanced grading, sound design/music beds, advanced reframing; efficiency codecs standard.
- **Backend/data:** **Postgres partitioning** of the largest tables; a **dedicated search engine** (OpenSearch) if transcript-search/cross-video features arrive; mature multi-pool autoscaling.
- **Infra:** mature Kubernetes (if adopted), multi-region storage/DR for critical artifacts, self-hosted observability.
- **Goal:** the full blueprint's capabilities, with cost-per-unit optimized for scale.

## 12.4 Production scale
- **Intelligence:** a model-serving fleet (owned GPUs) for the cost-dominant capabilities, frontier APIs reserved for the hardest tasks; aggressive per-task model routing.
- **Backend/data:** horizontally scaled edge, sharded/partitioned data where needed, mature caching, multi-region resilience.
- **Infra:** full IaC, mature CI/CD with progressive delivery, comprehensive observability and SLOs, cost governance.
- **Goal:** reliable, efficient operation at large volume — reached *incrementally*, never via a big-bang rewrite.

## 12.5 What stays stable vs. what gets replaced
- **Expected to remain stable (the bedrock):** PostgreSQL, Redis, FFmpeg, Docker, the Python/TypeScript language choice, S3-compatible storage, the React ecosystem, OpenAPI/REST contracts. These are mature standards we expect to run for the system's life.
- **Expected to evolve/be replaced (by design):** the *AI models* (continuously — this is the fast-moving frontier, abstracted for exactly this reason); the *queue broker* (Redis→RabbitMQ/managed); *orchestration* (managed containers→K8s); *deployment of models* (cloud API→self-hosted); *observability/auth/analytics* (managed→self-hosted where cost justifies); the *media compositor* (FFmpeg/ASS→FFmpeg+programmatic compositor). 
- **The principle:** the **bedrock infrastructure is chosen to never need replacing**, while the **fast-moving and cost-sensitive layers are deliberately abstracted to be replaced repeatedly without disturbing the bedrock.** Stability where stability is possible; replaceability where change is inevitable.

---

# Part 13 — Final CTO Essay

## "Choosing Technologies That Let Olympus Survive Ten Years"

### I. The question that should govern every technology choice

Most technology decisions are made by asking "what is the best tool for this job *today*?" It is the wrong question, or at least an incomplete one, because it optimizes for a moment in a system meant to last a decade. The right question — the one a CTO building something durable must ask — is "what set of choices lets this system *still be alive, maintainable, and improvable in ten years*?" These are not the same question, and they often have different answers. The tool that wins a benchmark today may be abandoned in three years; the framework that is fashionable now may have no hiring pool later; the model that is state-of-the-art this quarter will be ordinary by the next. A system that chases "best today" at every turn is a system perpetually rewriting itself, never compounding, always fragile. Olympus is meant to last, so every choice in this document was made against the ten-year question — and the answer to that question is almost never "the newest thing."

### II. Why architecture outlives tools

Here is the deepest truth of long-lived software: **the architecture outlives every tool that implements it.** The tools — the specific database, the specific queue, the specific model, the specific framework — will all be replaced, some of them several times, over a decade. What persists is the *shape*: the separation of concerns, the boundaries between components, the contracts through which they communicate, the discipline about what depends on what. A system whose architecture is sound can survive the replacement of any individual tool, because each tool sits in a well-defined place with a well-defined interface, and swapping it is a local operation. A system whose architecture is unsound dies when its tools age, because the tools are tangled together and none can be replaced without breaking the rest. This is why the MVP Engineering Architecture was designed and frozen *before* a single technology was chosen, and why this document is careful to place every technology *into* that architecture rather than letting the technologies define the structure. The architecture is the thing we are really building; the technologies are interchangeable parts we install into it. Ten years from now, Olympus may share *none* of the specific tools named in this document — and it will still be Olympus, because the architecture will be the same.

### III. Why modular systems are essential

Modularity is not an aesthetic preference or a best-practice checkbox; for a system meant to survive a decade in a fast-moving field, it is *survival itself.* The AI models Olympus depends on will change every few months — that is simply the reality of the frontier. A monolithic Olympus, where the model is woven through the codebase, would face an impossible choice every few months: rewrite large parts of the system to adopt a better model, or fall behind. Neither is survivable. A modular Olympus faces no such choice: the model sits behind a contract, and adopting a better one is a configuration change. The same logic applies to every fast-moving or cost-sensitive part — the queue, the orchestration, the storage provider, the deployment of models. Modularity converts the terror of change into a routine operation. It is what lets a small team keep a large, long-lived system current without ever stopping to rewrite it. In a field where the ground shifts monthly, the only systems that survive are the ones built to absorb that shifting *part by part* — and that is exactly what modularity provides. It is not optional for Olympus; it is the precondition of its longevity.

### IV. Why every dependency should be replaceable

It follows that **every dependency must be replaceable**, and this is a discipline that must be enforced deliberately, because the path of least resistance always leads to lock-in. It is easy — tempting, even — to reach directly for a vendor's convenient SDK, to let their data formats spread through your code, to build assuming their specific behavior. Each such shortcut saves an hour today and costs a migration later, and the migrations compound into a system that cannot move. The discipline is to wrap every dependency behind your own interface, to prefer open standards over proprietary ones, to depend on the *capability* (transcription, storage, reasoning) rather than the *vendor* (this specific API). This costs a little more upfront — an interface to design, an abstraction to maintain — and it buys something priceless: optionality. When a vendor raises prices, degrades, fails, or is simply beaten by a competitor, a system built on replaceable dependencies responds with a shrug and a swap; a system built on lock-in responds with a crisis or a surrender. Over ten years, every vendor relationship will be tested — prices change, companies fail, better options emerge — and the system that treated every dependency as replaceable is the system that survives those tests. Replaceability is how you stay free.

### V. Why engineering discipline beats chasing trends

The technology industry runs on novelty, and novelty is seductive: every month brings a new framework, a new database, a new paradigm promising to make everything better. The undisciplined team chases these, and pays for it — in half-migrations never finished, in expertise never accumulated, in production incidents from immature tools, in a codebase that is an archaeology of abandoned fashions. The disciplined team does the harder, less glamorous thing: it chooses boring, proven technology for the foundation; it spends its precious innovation budget *only* on its actual differentiation; it adopts the genuinely new only where there is a decisive, durable reason and only behind an interface; and it lets the rest of the industry's churn pass it by. This discipline looks unexciting from the outside and feels unexciting from the inside, and it is precisely what builds systems that last. The teams that win over a decade are not the ones that adopted the most new things; they are the ones that chose a small number of stable foundations, mastered them deeply, concentrated their creativity on the problem that actually mattered, and refused to be distracted. Engineering discipline is not the absence of ambition — it is ambition pointed at the right target: a system that still works, still ships, and still improves, ten years on. For Olympus, whose differentiation is the editing intelligence, discipline means being radically boring everywhere else so that *all* the team's creative energy goes into the one thing that makes Olympus Olympus.

### VI. The Technology Constitution

Let these stand as the technology constitution every Olympus engineer must follow:

> **1. Architecture outlives tools. Build the architecture first; install technologies into it. No tool ever dictates the structure; the structure dictates where tools go.**
>
> **2. Be boring on purpose, everywhere except the product. Choose proven, mature, well-supported technology for all infrastructure; spend the innovation budget only on Olympus's actual differentiation — the editing intelligence.**
>
> **3. Every dependency lives behind our own interface. Depend on capabilities, not vendors; prefer open standards; never let a convenient SDK or a proprietary format spread through the system.**
>
> **4. Every subsystem is replaceable, and we keep the exit. No technology is adopted without a named migration path. Optionality is a feature we never trade away.**
>
> **5. Models are commodities; the interfaces are the asset. Adopt the best model per task today; expect to replace it next quarter; make replacement a config change.**
>
> **6. Buy for reliability and speed now; build toward cost at scale — always behind an interface. Managed services where they buy reliability and velocity; self-host the cost-dominant pieces when volume justifies it; the system never notices the switch.**
>
> **7. Optimize cost through efficiency, never through quality. Reuse-once-compute-many, pay-per-use compute, sample-don't-saturate, lifecycle-clean, right-size models — but never lower the quality floor to save money.**
>
> **8. Minimize languages, systems, and moving parts. Every component is something a small team must understand and operate for years; fewer, deeper, more-mastered beats more, shallower, half-known.**
>
> **9. Reliability and discipline over novelty and hype. The goal is a system that still works in ten years — and that goal is reached by judgment, restraint, and proven foundations, not by chasing trends.**

A team that follows this constitution will not build a stack that is impressive today and dead in three years. It will build a stack that is *boring in all the right places and excellent in the one place that matters* — a foundation of proven, replaceable, well-mastered technology, with the team's full creativity concentrated on the editing intelligence that is Olympus's reason to exist. That is how you choose technologies that let a system survive ten years: not by predicting the future, but by building so that the future — whatever it brings — can be absorbed one replaceable part at a time, while the architecture, the discipline, and the product endure.

*Choosing technologies that let Olympus survive ten years. This document is the technology decision record and constitution that turns the MVP architecture into a concrete, buildable, durable stack.*

---

*End of Phase 3A / Prompt 2 — Technology Stack, AI Model Selection & Engineering Decisions.*
