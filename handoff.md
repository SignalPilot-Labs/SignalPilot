# Embedded Notebook Integration — Handoff

## What Was Done

The SignalPilot notebook frontend (from `sp-notebook/frontend/src/`) has been copied into the main web app at `signalpilot/web/notebook/`. It compiles successfully with Turbopack as part of the Next.js build — no iframe, no npm package, no pre-built chunks.

### Previous Approaches That Failed

1. **Vite lib-mode npm package** — Vite emits CJS interop helpers (`typeof require`, `require("react")`) in code-split chunks. Both Turbopack and webpack reject these at runtime. Tried: `stripCjsRequire` plugin, `.mjs` extensions, `inlineDynamicImports`, `commonjsOptions.transformMixedEsModules`. None worked.

2. **tsup-built npm package** — Same `require("react")` issue. tsup's output is clean but Next.js's module evaluation wraps chunks with its own CJS interop.

3. **pnpm workspace link** — Path alias conflict (`@/` used by both projects). Also triggered 50+ zombie Node processes from workspace package resolution.

4. **Middleware proxy** — Works but the notebook takes over the full page (no sidebar). Not a true embed.

### What Finally Worked

Copied `sp-notebook/frontend/src/` → `signalpilot/web/notebook/`. Both projects are Next.js, same React version, same Turbopack. The notebook code compiles as part of the web app — zero bundler interop issues.

## Current State

### Files

```
signalpilot/web/
  notebook/                ← copied from sp-notebook/frontend/src/
    core/                  ← kernel, websocket, state, runtime
    components/            ← editor, file tree, git panel, data table, etc.
    embed/                 ← SignalpilotEditor, SpEmbedProviders, createSignalpilotClient
    mount.tsx              ← app initialization
    css/                   ← notebook CSS (globals.css has @config path fixed)
    utils/                 ← id-tree.tsx had `delete()` renamed to `deleteById()`
    ...
  components/notebook/
    notebook-embed.tsx     ← wrapper component that creates SignalpilotClient and renders SignalpilotEditor
  app/projects/
    page.tsx               ← projects page with embedded notebook (replaces iframe)
```

### Path Aliases

- Web app uses `~/` → `signalpilot/web/*` (changed from `@/` to avoid conflict)
- Notebook code uses `@/` → `signalpilot/web/notebook/*`
- Configured in `tsconfig.json`:
  ```json
  "paths": {
    "~/*": ["./*"],
    "@/*": ["./notebook/*"]
  }
  ```

### Package Manager

The project uses **pnpm** with a workspace at `SPEcosystem/pnpm-workspace.yaml`:
```yaml
packages:
  - "sp-dev-work/signalpilot/web"
  - "sp-notebook/packages/*"    # @sp-team/llm-info, sp-api, smart-cells
```

The notebook's internal workspace packages (`@sp-team/llm-info`, `@sp-team/sp-api`, `@sp-team/smart-cells`) are linked from `sp-notebook/packages/` via `workspace:*` in package.json.

### Build

```bash
cd SPEcosystem
pnpm install --filter signalpilot-web
cd sp-dev-work/signalpilot/web
npx next build   # or: npm run dev
```

Build passes with `typescript.ignoreBuildErrors: true` in `next.config.ts`. There are ~10 TypeScript type errors (mostly `JSON.parse` returning `unknown` in strict mode + notebook code expecting `reactCompiler`). These don't affect runtime.

### next.config.ts

Key settings merged from the notebook's config:
- `serverExternalPackages` for Tailwind native addons
- Turbopack `resolveAlias` for vscode-jsonrpc pnpm resolution
- Turbopack `rules` for CSS-as-string imports (raw-loader for glide-data-grid, swiper, SVGs)

### Fixes Applied

1. **`delete()` → `deleteById()`** in `notebook/utils/id-tree.tsx` (lines 505, 782) and all callers (~44 files). SWC transpiles class method `delete()` as `function delete()` which is a syntax error (`delete` is a reserved word).

2. **`@/` → `~/`** in all web app files (~352 imports). Freed `@/` for the notebook's path alias.

3. **`tailwind.config.cjs`** copied to `notebook/` and CSS `@config` path fixed from `../../` to `../`.

4. **`lucide-react`** upgraded to `^0.563.0` for newer icons (`FunnelPlusIcon`, `RulerDimensionLine`).

5. **125 notebook dependencies** added to web app's `package.json` (CodeMirror, jotai, react-aria, plotly, mermaid, etc.).

## What Needs to Be Done

### 1. Pod Integration

The `notebook-embed.tsx` component creates a `SignalpilotClient` with `runtimeConfig.url` pointing to the gateway's notebook proxy:

```typescript
const runtimeUrl = `${gatewayUrl}/notebook/${sessionId}`;

const client = createSignalpilotClient({
  runtimeConfig: { url: runtimeUrl, lazy: false },
  writeDocumentTitle: false,
});
```

This URL is where the notebook's WebSocket kernel connects. The pod must be running and the session must exist. The flow:

1. User clicks "Open IDE" on `/projects` page
2. `createNotebookSession({ project_id, branch })` → returns `session.id`
3. Gateway creates K8s pod, waits for it to be ready
4. `NotebookEmbed` mounts with `sessionId` → creates client → connects WebSocket to pod via gateway proxy
5. Notebook renders inline with sidebar visible

The current `app/projects/page.tsx` has this flow wired up but hasn't been E2E tested with the embedded component (only with the iframe).

### 2. CSS Integration

The notebook's CSS (`notebook/css/globals.css`) uses Tailwind v4 with `@config "../tailwind.config.cjs"`. This may conflict with the web app's own Tailwind setup. The notebook's CSS is scoped under `.sp-root` via PostCSS (already configured in the embed).

Need to verify:
- Notebook styles don't leak into the web app
- Web app styles don't break the notebook
- The `.sp-root` wrapper in `SignalpilotEditor` properly contains styles

### 3. Runtime Errors

The notebook boots via `createSignalpilotClient` → `SpEmbedProviders` → `initStoreOnce()` → `SpApp`. This chain needs:
- A valid runtime URL (pod WebSocket endpoint)
- The pod to be running and healthy
- Proper auth token flow (session JWT for pod API calls)

Without a running pod, the notebook will show connection errors — this is expected.

### 4. TypeScript Strictness

Re-enable `typescript.ignoreBuildErrors: false` after fixing:
- `JSON.parse` returns `unknown` in strict mode (~5 web app files need `as` casts)
- Notebook code expects `reactCompiler: true` which adds stricter type checking
- The `deleteById` rename may have broken `.delete()` calls on Map/Set (verify with tests)

### 5. Keeping Notebook Code in Sync

The notebook source in `signalpilot/web/notebook/` is a point-in-time copy from `sp-notebook/frontend/src/`. When the notebook team pushes updates:

```bash
# Update notebook source
rm -rf signalpilot/web/notebook
cp -r ../sp-notebook/frontend/src/ signalpilot/web/notebook/
# Re-apply fixes
sed -i 's/  delete(/  deleteById(/g' notebook/utils/id-tree.tsx
# ... other patches
```

Consider automating this with a script or Git submodule.

## Key Files

| File | Purpose |
|------|---------|
| `signalpilot/web/notebook/` | Notebook source (copied from sp-notebook) |
| `signalpilot/web/notebook/embed/` | Embed entry point (SignalpilotEditor, createSignalpilotClient) |
| `signalpilot/web/components/notebook/notebook-embed.tsx` | Wrapper component used by projects page |
| `signalpilot/web/app/projects/page.tsx` | Projects page with embedded notebook |
| `signalpilot/web/next.config.ts` | Turbopack rules, resolve aliases |
| `signalpilot/web/tsconfig.json` | Path aliases: `~/` (web), `@/` (notebook) |
| `SPEcosystem/pnpm-workspace.yaml` | Workspace config |
| `signalpilot/web/notebook/utils/id-tree.tsx` | `delete()` → `deleteById()` fix |
| `signalpilot/web/notebook/css/globals.css` | Tailwind config path fix |

## Environment

- Next.js 16.2.6 with Turbopack (default)
- React 19.2.4
- pnpm 10.30.3
- Node.js 22+
- Gateway at `localhost:3300` (local) or `gateway.signalpilot.ai` (prod)
- K3s for notebook pods (local or EC2)
