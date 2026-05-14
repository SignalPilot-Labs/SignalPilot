# workspaces-web

Next.js 16 (App Router) frontend for the Workspaces API. Renders workspace charts at `/dashboards/<workspace-id>`.

## Port

Development: **3500**

## Routes

- `/` — Landing page
- `/dashboards/[id]` — Workspace chart dashboard (renders all charts for a workspace)
- `/sign-in/[[...sign-in]]` — Clerk-hosted sign-in page (cloud mode only; returns 404 in local mode)

## Environment variables

### Mode selector

| Variable | Required | Description |
|---|---|---|
| `WORKSPACES_MODE` | No (default: `"local"`) | `"local"` or `"cloud"`. All other vars depend on this. |

### Local mode (`WORKSPACES_MODE=local` or unset)

| Variable | Required | Description |
|---|---|---|
| `WORKSPACES_API_URL` | Yes (server-only) | Base URL of the workspaces API, e.g. `http://workspaces-api:3400` |
| `SP_LOCAL_API_KEY` | Yes (server-only) | Local API key forwarded as `Authorization: Bearer` to workspaces API |

### Cloud mode (`WORKSPACES_MODE=cloud`)

| Variable | Required | Description |
|---|---|---|
| `WORKSPACES_API_URL` | Yes (server-only) | Base URL of the workspaces API |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Yes | Clerk publishable key (exposed to browser via Next.js public prefix) |
| `CLERK_SECRET_KEY` | Yes (server-only) | Clerk secret key (never sent to browser) |

`SP_LOCAL_API_KEY` is **not read** in cloud mode. Do not pass it.

All non-`NEXT_PUBLIC_*` variables are server-only — never sent to the browser.

### Backend cloud-mode variables (`workspaces_api`)

The API service requires its own Clerk configuration:

| Variable | Required | Description |
|---|---|---|
| `SP_DEPLOYMENT_MODE` | Yes | Set to `"cloud"` |
| `SP_CLERK_JWKS_URL` | Yes | Clerk JWKS endpoint URL |
| `SP_CLERK_ISSUER` | Yes | Clerk Frontend API URL (matches the Clerk instance's issuer) |
| `SP_CLERK_AUDIENCE` | No | Audience to validate in JWTs. **Optional** — omit unless the operator pins a JWT template audience. If set, must match the audience in the `workspaces` JWT template. |

**Clerk JWT template name**: the web app requests a token with `template: "workspaces"`. The Clerk dashboard must have a JWT template named exactly `workspaces`. The backend validates `sub`, `iss`, and `exp` claims; `aud` validation is only applied when `SP_CLERK_AUDIENCE` is set.

## Dev server (host) — local mode

Before running `npm run dev`, export the local-mode env vars:

```sh
export WORKSPACES_API_URL=http://localhost:3400
export SP_LOCAL_API_KEY=$(cat /shared/local_api_key)
npm run dev
```

The API is expected to run on port 3400. In Docker Compose, `WORKSPACES_API_URL=http://workspaces-api:3400` resolves via the internal network.

## Dev server — cloud mode

```sh
export WORKSPACES_MODE=cloud
export WORKSPACES_API_URL=http://localhost:3400
export NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
export CLERK_SECRET_KEY=sk_test_...
npm run dev
```

## Stack

- Next.js 16 (App Router, Server Components)
- TypeScript (strict)
- Tailwind CSS v4 (`@theme` tokens in `globals.css`)
- Apache ECharts (tree-shaken from `echarts/core`)
- Clerk (`@clerk/nextjs@^6`) — cloud mode only; static import, conditionally rendered
- Vitest + Testing Library for unit tests

## Notes

- "Dashboard id" equals workspace id until a Dashboard entity is introduced.
- Page copy says "Workspace charts" — URL stays `/dashboards/[id]`.
- All API fetches are server-side. No client-side data fetching in this version.
- Cloud mode bundles `@clerk/nextjs` in all middleware and layout chunks regardless of mode (ESM-only package, no conditional require). The bundle overhead is small.
- No `useUser()` / `<UserButton />` / client-side Clerk hooks in this version.
