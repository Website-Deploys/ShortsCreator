# Project Management & Asset Library

The **production management layer** of Project Olympus. It is **not** an AI
engine — it lets creators *manage* everything the eight intelligence/workflow
engines produce: source videos, clips, renders, exports, version history,
activity, storage, search, and dashboard statistics.

It is **fully additive**. It reads every engine's real output read-only and adds
a small amount of state of its own under a dedicated `library/` storage
namespace. **No engine and no existing API was modified.**

---

## Design principles

- **Read-only over engine data.** The library loads each engine's output through
  its existing repository and never writes back. The only writes it performs are
  to its own `library/` namespace (favorites, tags, archive, captured versions,
  activity log) and the explicitly-requested cleanup operations.
- **Honesty-first.** Every figure reflects real stored state. A value an engine
  did not produce is reported as `null`/UNKNOWN — never fabricated. Sizes are
  measured from the real filesystem; if a backend cannot report a size cheaply,
  it is reported as unknown rather than guessed.
- **Mirrors the Olympus layering:** entities → contracts → repositories →
  module → service → schemas → routes → frontend → tests.

---

## Architecture

| Layer | Location |
| --- | --- |
| Entities | `src/olympus/domain/entities/library.py` |
| Contracts (ports) | `src/olympus/domain/contracts/library.py` |
| Repositories | `src/olympus/data/repositories/{version,activity,library_meta}_repository.py` |
| Aggregation module | `src/olympus/project_management/` (`sizes`, `inventory`, `search`, `dashboard`) |
| Service | `src/olympus/services/project_management/service.py` (`LibraryService`) |
| API schemas / routes | `src/olympus/api/v1/schemas/library.py`, `routes/library.py` |
| Frontend | `frontend/src/app/library/page.tsx`, `frontend/src/lib/library.ts` |
| Tests | `tests/unit/test_project_management.py`, `frontend/src/lib/library.test.ts` |

### Storage namespace (the only writes)

```
library/
  versions/{project_id}/{engine}/index.json + v{n}.json   # append-only snapshots
  activity/{project_id}.json | _global.json               # recorded PM actions
  meta/{project_id}.json                                  # favorites, tags, archive
```

It reads (never writes) the engines' namespaces: `projects/`, `analysis/`,
`story/`, `virality/`, `planning/`, `editing/`, `render/`, `optimization/`,
`workflow/`.

---

## Features

1. **Asset Library** — every source video, clip, render, export, and thumbnail,
   aggregated across projects with kind/tag/favorite/archive filtering.
2. **Version History** — append-only, checksum-deduplicated snapshots of each
   engine's output (`Analysis v1`, `Story v2`, …). History is never overwritten.
   Because the engines themselves overwrite their current output, the library
   captures versions when asked (`POST …/versions/capture`); it does not invent
   past versions that predate the library.
3. **Clip Library** — every clip with its real per-clip facts: duration, viral
   score (the Clip Planner's per-clip quality score), platform, status,
   thumbnail, render version, source project.
4. **Export Library** — every rendered export with the renderer's **measured**
   resolution, codec, bitrate, file size, render time, and download status.
5. **Global Search** — across projects, clips, videos, exports, metadata, tags.
6. **Dashboard** — total projects, videos processed, minutes analyzed, clips
   generated, renders completed, exports, average viral score, storage usage.
7. **Storage Inspector** — per-project consumption broken down by namespace
   (uploads, analysis, story, virality, planning, editing, renders, exports,
   optimization, logs).
8. **Cleanup Tools** — delete temporary files, delete failed renders, delete
   unused (unreferenced) renders; archive / restore projects. These are the only
   destructive actions and each reports exactly what it removed.
9. **Activity Feed** — real events: project created, workflow started/finished,
   stage finished, version captured, archived/restored, cleanup performed.
   Derived from real project + workflow state, merged with recorded PM actions.
10. **Read-only UI** — a `/library` dashboard with Dashboard, Assets, Clips,
    Exports, Activity, and Storage views. Everything is read-only except the
    clearly-labelled cleanup/archive controls.

---

## API (prefix `/api/v1/library`)

```
GET  /dashboard
GET  /assets         ?kind=&project_id=&q=&tag=&favorite=&archived=
GET  /clips          ?project_id=&q=&platform=&status=&archived=
GET  /exports        ?project_id=&platform=&archived=
GET  /search         ?q=&limit=
GET  /activity       ?project_id=&limit=
GET  /storage        ?project_id=
GET  /projects/{id}/versions
POST /projects/{id}/versions/capture
GET  /projects/{id}/versions/{engine}
GET  /projects/{id}/versions/{engine}/{version}
POST /projects/{id}/favorite           {favorite}
POST /projects/{id}/tags               {tag}
DELETE /projects/{id}/tags/{tag}
POST /projects/{id}/archive
POST /projects/{id}/restore
POST /cleanup/temp-files               ?project_id=
POST /cleanup/failed-renders           ?project_id=
POST /cleanup/unused-renders           ?project_id=
```

---

## Honesty notes & limitations

- **Clip "viral score"** is the Clip Planner's per-clip quality score (the only
  genuinely per-clip signal); the project-level virality assessment lives on the
  Virality tab. This is labelled, not conflated.
- **Version history** begins when the library first captures an output. It cannot
  reconstruct versions the engines overwrote before a capture was taken — it
  never fabricates history.
- **Sizes** are measured via the local-disk backend's real file sizes. A non-local
  backend that does not expose a path reports size as unknown rather than reading
  whole media files into memory.
- **Cleanup** removes only what each operation names: temp files
  (`render/{id}/work/`), clip files of `FAILED` render runs, or clip files no
  longer referenced by the current render manifest. Rendered outputs in use are
  never touched.
