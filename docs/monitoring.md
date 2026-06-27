# Production Monitoring & Analytics

The **operational observability layer** of Project Olympus. It is **not** an AI
engine — it lets Olympus monitor *itself* like a real production SaaS: system
health, engine performance, the live queue, storage, failures, usage, cost
estimation, audit logs, and alerts, surfaced through an admin dashboard.

It is **fully additive and strictly observational**. It reads the real,
persisted execution state that the eight engines, the Workflow Orchestration
Engine, and the Asset Library already wrote, and aggregates it read-only. It adds
a small amount of state of its own under a dedicated `monitoring/` storage
namespace (an append-only audit log and captured storage snapshots).
**No engine, no workflow, and no existing API was modified, and it never changes
engine behaviour — it only observes.**

---

## Design principles

- **Observational only.** Monitoring loads each engine/workflow/library output
  through its existing repository (read-only) and reads the live worker/queue
  state from the running workflow service. It never writes back to any of them
  and never influences execution.
- **Honesty-first / no fabrication.** Every figure is a *measured* value. Any
  quantity that cannot be measured in the current environment is reported as
  `null` / UNKNOWN (e.g. system-wide memory without `psutil`, LLM token usage and
  GPU time which are not instrumented). Cost is always an explicit **estimate**,
  never billing.
- **UNAVAILABLE is not a failure.** A stage an engine honestly could not run
  (e.g. a model not configured) is `UNAVAILABLE` — it is counted separately and
  is **never** treated as a failure. Only genuine `FAILED`/`DEAD` states are
  failures.
- **Mirrors the Olympus layering:** entities → contracts → repositories →
  module (`monitoring/`) → service → schemas → routes → frontend → tests.

---

## Architecture

| Layer | Location |
| --- | --- |
| Entities | `src/olympus/domain/entities/monitoring.py` |
| Contracts (ports) | `src/olympus/domain/contracts/monitoring.py` |
| Repositories | `src/olympus/data/repositories/{audit,metrics_snapshot}_repository.py` |
| Analytics module | `src/olympus/monitoring/` (`system`, `metrics`, `workflow_analytics`, `storage_analytics`, `failures`, `cost`, `alerts`, `audit`) |
| Service | `src/olympus/services/monitoring/service.py` (`MonitoringService`) |
| API schemas / routes | `src/olympus/api/v1/schemas/monitoring.py`, `routes/monitoring.py` |
| Frontend | `frontend/src/app/admin/page.tsx`, `frontend/src/lib/monitoring.ts` |
| Tests | `tests/unit/test_monitoring.py`, `frontend/src/lib/monitoring.test.ts` |

### Storage namespace (the only writes)

```
monitoring/
  audit/log.json            # append-only recorded audit entries (cap 5000)
  snapshots/storage.json    # captured storage trend points (dedup/hour, cap 500)
```

It reads (never writes) every engine namespace plus `workflow/` and `library/`.

---

## Features

1. **System Health Dashboard** — overall health derived from engine health, the
   queue, and host disk pressure.
2. **Engine Performance Analytics** — per-engine execution time (avg/p95), wait
   time, queue delay, retries, failures, cancellation/completion rates, average
   confidence, throughput, and concurrent executions — all measured from the
   uniform per-stage records every engine persists.
3. **Queue Monitoring** — queued/running/dead/blocked jobs, stuck-job detection,
   queue latency, and live worker utilization (from the running workflow service
   when attached; otherwise counts are derived from persisted jobs).
4. **Storage Analytics** — real byte usage per top-level namespace plus a trend
   series accumulated from captured snapshots.
5. **Performance Profiling** — host CPU count, load average, process CPU seconds
   and peak RSS, and disk usage, via the standard library.
6. **Failure Analytics** — failures aggregated by engine, exception type, and
   project, with recent records carrying the *real* recorded error (never a
   fabricated cause). UNAVAILABLE stages are excluded.
7. **Usage Analytics** — projects, videos processed, minutes analyzed, clips,
   renders, exports, workflows run, total stage executions, busiest engine.
8. **Cost Estimation** — an estimate from measured work (transcription minutes,
   render minutes, storage GB, process CPU hours) at configurable rates. LLM
   tokens and GPU time are UNKNOWN (not instrumented) and contribute nothing.
9. **Audit Logs** — an immutable feed derived from real persisted state (workflow
   histories, library activity, render/optimization executions) merged with an
   append-only recorded log.
10. **Admin Dashboard** — a combined snapshot (health, engines, queue, system,
    usage, storage, alerts, recent failures, recent audit).
11. **Alerts** — informational only (no notifications): dead jobs, stuck workers,
    large storage, disk pressure, repeated failures, high retry rates, low
    confidence. Each carries the evidence it was derived from; UNKNOWN metrics
    produce no alert.

---

## API

All endpoints are `GET` under `/api/v1/monitoring` and are read-only:

| Endpoint | Returns |
| --- | --- |
| `/health` | overall health + engine/system/queue |
| `/engines` | per-engine performance metrics |
| `/workflows` | workflow analytics (duration, idle, critical path, bottlenecks) |
| `/queue` | live queue + worker snapshot |
| `/system` | host system metrics |
| `/storage?capture=` | storage by namespace + trend (`capture=true` appends a point) |
| `/failures` | failure aggregation |
| `/usage` | usage totals |
| `/cost` | cost estimate |
| `/audit?limit=` | audit feed (newest first) |
| `/alerts` | informational alerts |
| `/admin` | combined admin snapshot |

---

## Honesty notes & known limitations

- **System memory** is UNAVAILABLE without `psutil` and is reported as `null`
  (listed in `unavailable`), never estimated. Disk, CPU count, load average, and
  process CPU/RSS are measured via the standard library.
- **LLM tokens and GPU time** are not instrumented anywhere in the platform, so
  their cost lines are UNKNOWN with a zero contribution and a clear note. Cost
  rates are indicative placeholders, not a price list.
- **Downloads** are not tracked by any hook, so they are *not* audited — noted
  here as a transparency limitation rather than fabricated.
- **Storage trend** starts empty and accumulates only from captured snapshots
  (the `/storage?capture=true` endpoint or the admin snapshot capture path).
- **Worker pool** counts are live only when the running workflow service is
  attached; otherwise queue counts are derived from persisted workflow jobs and
  worker counts are honestly zero.
- The current persistence is storage-backed JSON; a database-backed
  implementation can replace each repository behind the same contract without
  touching the service, API, or frontend.
