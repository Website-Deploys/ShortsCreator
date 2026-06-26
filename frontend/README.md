# Olympus Web Client

The thin presentation layer for Project Olympus. Built with **Next.js (App
Router) + TypeScript + Tailwind CSS + TanStack Query**, per the technology
decisions. It is "server-state first": most UI state is server state managed by
TanStack Query.

## Requirements

- **Node.js 20+** (Node 22 recommended)
- The Olympus backend running (see the repository root `README.md`)

## Quick start

```bash
cp .env.example .env.local        # point NEXT_PUBLIC_API_BASE_URL at the backend
npm install
npm run dev                       # http://localhost:3000
```

With the backend running on `http://localhost:8000`, the navigation bar shows a
live "backend vX.Y" indicator - a real call against `GET /system/info` that
proves the full frontend -> backend wiring today.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Run the dev server (hot reload). |
| `npm run build` | Production build. |
| `npm run start` | Serve the production build. |
| `npm run lint` | Lint with `eslint-config-next`. |
| `npm run typecheck` | Type-check with `tsc --noEmit`. |

## Structure

```
frontend/
├── src/
│   ├── app/                    # App Router pages
│   │   ├── page.tsx            #   landing
│   │   ├── dashboard/          #   project list
│   │   ├── upload/             #   create a project (URL paste)
│   │   ├── processing/[id]/    #   honest, polled progress
│   │   ├── results/[id]/       #   finished Shorts
│   │   ├── settings/           #   default preferences
│   │   ├── profile/            #   creator identity (DNA seed)
│   │   ├── layout.tsx          #   root layout + providers
│   │   ├── providers.tsx       #   TanStack Query client
│   │   └── globals.css         #   Tailwind entry
│   ├── components/             # shared UI (Nav, BackendStatus, ui/*)
│   └── lib/                    # config, typed apiClient, types, query hooks
└── (config: package.json, tsconfig, tailwind, postcss, next.config)
```

Pages whose backend endpoints arrive in Milestone 2 (projects, clips) degrade
gracefully today - they show clear, honest states rather than erroring - and
are fully wired to consume those endpoints the moment they ship.
