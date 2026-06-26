# Project Olympus

An AI Creative Studio that turns one long-form video into multiple premium,
creator-ready Shorts.

This repository contains the **design blueprint** (`docs/architecture/`), the
**engineering plans** (`docs/engineering/`), and the **backend implementation**
(`src/olympus/`). This release is the **repository foundation**: all the wiring,
abstractions, and infrastructure on which the rest of Olympus is built. It
contains no business logic yet — but it compiles, starts, and is fully tested.

---

## Requirements

- **Python 3.11+**
- **[uv](https://github.com/astral-sh/uv)** for dependency management
- **Docker** (optional, for local Postgres + Redis)
- **FFmpeg** (optional; only needed once rendering is implemented)

## Quick start

```bash
# 1. Configure your environment
cp .env.example .env

# 2. Install dependencies into a virtualenv
make install            # == uv venv && uv pip install -e ".[dev]"

# 3. (Optional) start local infrastructure — Postgres + Redis
make compose-up

# 4. Run the API
make run-api            # http://localhost:8000

# 5. In another terminal, run a worker (needs Redis from step 3)
make run-worker
```

The API starts **without** Postgres or Redis (it uses the local-disk storage
backend and a no-op transcription provider by default). Database-backed
endpoints and the queue require the infrastructure from `make compose-up`.

### Verify it works

```bash
curl http://localhost:8000/api/v1/health/live      # {"status":"alive"}
curl http://localhost:8000/api/v1/system/info      # version + active adapters
open http://localhost:8000/docs                    # interactive API docs (dev only)
```

### Quality gates

```bash
make lint        # ruff
make typecheck   # mypy (strict)
make test        # pytest
```

---

## Repository layout

```
olympus/
├── pyproject.toml          # deps, build, and tooling config (ruff/mypy/pytest)
├── .env.example            # environment configuration template
├── Makefile                # developer task runner (uv-based)
├── docker-compose.yml      # local Postgres + Redis
├── deploy/Dockerfile       # backend container image (API + worker)
├── docs/                   # the design blueprint + engineering plans
│   ├── architecture/       #   the ten permanent design documents
│   └── engineering/        #   MVP architecture + technology decisions
├── src/olympus/            # the backend package
│   ├── platform/           #   config, logging, errors, monitoring
│   ├── domain/             #   technology-free core: the contracts (ports)
│   ├── data/               #   adapters: database connection + storage backends
│   ├── services/           #   shared services: the queue (Celery)
│   ├── ai/                 #   AI adapters behind the AI contracts
│   ├── rendering/          #   rendering adapters behind the rendering contract
│   ├── api/                #   the HTTP edge: FastAPI app, middleware, routes
│   ├── apps/               #   deployable entry points: backend_api, workers
│   └── utils/              #   small dependency-free helpers
└── tests/                  # unit tests mirroring the package layout
```

## Architecture in one paragraph

A **thin synchronous edge** (`api` / `apps.backend_api`) accepts requests,
validates them, and enqueues work; a **deep asynchronous core**
(`apps.workers`, `services.queue`) does the heavy lifting. The **domain**
defines abstract *contracts* (storage, AI, rendering); **adapters** in `data`,
`ai`, and `rendering` implement them; **factories** select the configured
adapter from settings. Every external dependency sits behind a contract, so it
is replaceable without touching callers — the discipline that lets Olympus
evolve toward the full blueprint one layer at a time.

See `docs/engineering/` for the full MVP architecture and technology decisions,
and `docs/architecture/` for the design blueprint.
