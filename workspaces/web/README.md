# workspaces-web

Next.js 15 (App Router) frontend for the Workspaces API. Renders workspace charts at `/dashboards/<workspace-id>`.

## Port

Development: **3500**

## Routes

- `/` — Landing page
- `/dashboards/[id]` — Workspace chart dashboard (renders all charts for a workspace)

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `WORKSPACES_API_URL` | Yes (server-only) | Base URL of the workspaces API, e.g. `http://workspaces-api:3400` |
| `SP_LOCAL_API_KEY` | Yes (server-only) | Local API key for the workspaces API |

Both variables are **server-only** — never prefixed with `NEXT_PUBLIC_*` and never sent to the browser.

## Dev server (host)

Before running `npm run dev`, export both env vars:

```sh
export WORKSPACES_API_URL=http://localhost:3400
export SP_LOCAL_API_KEY=$(cat /shared/local_api_key)
npm run dev
```

The API is expected to run on port 3400. In Docker Compose, `WORKSPACES_API_URL=http://workspaces-api:3400` resolves via the internal network.

## Stack

- Next.js 16 (App Router, Server Components)
- TypeScript (strict)
- Tailwind CSS v4 (`@theme` tokens in `globals.css`)
- Apache ECharts (tree-shaken from `echarts/core`)
- Vitest + Testing Library for unit tests

## Notes

- "Dashboard id" equals workspace id until a Dashboard entity is introduced.
- Page copy says "Workspace charts" — URL stays `/dashboards/[id]`.
- All API fetches are server-side. No client-side data fetching in this version.
- Cloud auth (Clerk JWT) is deferred to a follow-up round.
