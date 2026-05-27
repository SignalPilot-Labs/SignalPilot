# Embedded Notebook Integration — Handoff 2

## What Was Done This Session

### Architecture: NotebookContext + NotebookBoot
Replaced the scattered initialization system with a clean two-component architecture:

- **`NotebookContext`** (`components/notebook/notebook-context.tsx`): React context holding all runtime config (gatewayUrl, sessionId, token, apiKey, project, branch, file). Set once at the page level by `projects/page.tsx`. Provides `useNotebookConfig()` hook and `getNotebookConfig()` for non-React code.

- **`NotebookBoot`** (`components/notebook/notebook-boot.tsx`): Single component handling the entire boot sequence: health check → sync-down → session reuse → client creation. Renders `SignalpilotEditor` only when ready.

- **`notebook-embed.tsx`** was deleted — replaced by NotebookBoot.

### API Layer: apiCall() / kernelCall()
Created `notebook/core/network/api-call.ts` with two clean functions:

- **`apiCall(path, body?)`**: HTTP to pod. Waits for health check only. Used by file tree, git panel, dbt panel, home page.
- **`kernelCall(path, body?)`**: Same + waits for kernel WebSocket OPEN.
- **`cachedApiCall(path, body?, {ttl})`**: Cached variant with 5s TTL.

File tree (`state.tsx`), home page, gallery page, raw file editor all switched from `requestClientAtom` → direct `apiCall()`. The `requests-lazy.ts` action system stays for kernel operations.

### Performance Fixes
- **Event loop blocking**: `ws_endpoint.py` wraps `connector.connect()` in `asyncio.to_thread()` so kernel `Process.start()` doesn't block other HTTP requests. Before: 4s per parallel request during kernel spawn. After: 12-17ms.
- **RuntimeManager.markHealthy()**: Skips redundant health check retry loop when boot already verified health.
- **Session reuse**: NotebookBoot finds existing pod session for the target file and reuses its ID via `setSessionId()` instead of generating a new one that fights with SP_ALREADY_CONNECTED.
- **Sync gate removed**: The `waitForProjectSync` deferred system was deleted. It caused 10-second hangs when `edit-app.tsx`'s effect queued behind `useWebSocket`'s effect.
- **Faster polling**: Gateway pod polling 2s→0.5s, readiness probe 5s→1s.
- **Notebook image**: 2.85GB→2.33GB. Bytecode pre-compilation, eliminated chown layer duplication, consolidated pip installs.

### File Path Fixes
- `edit-app.tsx`: Path canonicalization uses `segments.slice(2)` (not 3) — structure is `{projectId}/{projectName}/rest`, not `{id}/{name}/{branch}/rest`.
- `edit-app.tsx`: Resolves relative URL file params to absolute using `dbtProjectDirAtom` before calling `openFileInTab`.
- File picker now generates correct relative paths (`models/schema.yml` not `schema.yml`).

### Other Fixes
- dbt panel: waits for kernel connection + retries with backoff for project detection.
- dbt pre-fetch: uses `apiCall()` instead of `getApiHeaders()` (avoids store proxy blocking).
- Raw file editor: uses `apiCall()` for file operations.
- WebSocket: `cancelled` flag prevents zombie connections from Strict Mode double-invoke.
- Auto-takeover on SP_ALREADY_CONNECTED with retry.
- Close reason forwarding in gateway WebSocket proxy.
- Button-in-button HTML fix in dbt-panel.
- ReorderableList MutationObserver fix for React Aria drag focus issue.
- CSP: ws:// origins, base-uri, img-src for gateway.
- File tree open-state pruned on project switch.

### sp-notebook Changes
- Frontend stripped (deleted `frontend/`, `_static/`, updated Makefile/turbo/pnpm config).
- Kernel optimizations: `forkserver` on Linux with preloaded modules, auto-instantiate in EDIT mode, pre-warm kernel pool.
- `asyncio.to_thread(connector.connect)` in ws_endpoint.py.
- `setSessionId()` added to `kernel/session.ts`.

## Current State

### What Works
- Deep-link URLs: `http://localhost:3200/projects?project={id}&branch=main&file=notebooks/intro.py` auto-launches, renders file tree + content in ~3-4s on hot pod.
- Project creation: scaffold pipeline (sync → scaffold → git stage/commit/push) all 200s.
- File tree: uses `apiCall()` directly, not blocked by kernel.
- dbt panel: detects project after sync-down, pre-fetched during boot.
- Agent chat: connects and responds.
- Session reuse: reconnects to existing pod sessions instead of fighting SP_ALREADY_CONNECTED.
- Event loop: HTTP requests not blocked during kernel spawn.
- Cold start: ~10s from navigate to file visible (includes pod creation).

### What's Broken
**CodeMirror cell editing is broken.** The notebook cells render code (syntax highlighting works) but:
- Cursor positioning is wrong (can only type at start of content)
- No visible caret/cursor effects
- Ctrl+S opens browser "Save As" instead of saving the notebook
- Raw file editor (which uses `@uiw/react-codemirror`) works fine

**Root cause identified**: Two copies of `style-mod` (CodeMirror's CSS injection library) exist:
1. `SPEcosystem/node_modules/.pnpm/style-mod@4.1.3/` (workspace root)
2. `sp-notebook/node_modules/.pnpm/style-mod@4.1.3/` (sp-notebook's store)

Turbopack bundles one copy for some CM imports and the other for others. `StyleModule` tracks injected styles per-module-instance. When two copies exist, styles registered by one aren't found by the other → CodeMirror's CSS never gets injected → editor renders content but has no cursor/layout CSS.

**Evidence**: `document.adoptedStyleSheets.length === 0` and only 1 `<style>` tag with `.cm-` rules (should be dozens).

**Fix attempts that failed**:
- `resolveAlias` in `next.config.ts` turbopack config — Windows paths break Turbopack dev server ("windows imports are not implemented yet")
- Adding `style-mod` as direct dependency — breaks imports from sp-notebook packages
- CSS overrides in globals.css — too aggressive, breaks notebook layout

**Likely fix direction**: 
- Delete `sp-notebook/node_modules` entirely and reinstall from workspace root only
- Or configure pnpm to hoist `style-mod` / `@codemirror/*` to workspace root with `pnpm-workspace.yaml` overrides
- Or use webpack's `resolve.alias` in `next.config.ts` for production build only (Turbopack can't handle it on Windows)
- Or move to a single `node_modules` by making sp-notebook packages not have their own pnpm store

### Loading States (Simplified)
The projects page has exactly 3 states:
1. **`"loading"`** — checking for session, auto-launching on deep-link
2. **`"no-session"`** — show "Open IDE" landing page
3. **`"ready"`** — session exists, render `NotebookProvider` + `NotebookBoot`

Deep-link URLs (`?project=...`) start in `"loading"` (never show landing page).

## How to Run

### Local Development
```bash
cd SPEcosystem/sp-dev-work/signalpilot/web
pnpm run dev  # or: npm run dev
# → http://localhost:3200
```

### Docker Stack
```bash
cd SPEcosystem/sp-dev-work
docker compose up --build
# Gateway: localhost:3300, Web: localhost:3200, K3s: localhost:6443
```

### Production Web Build
```bash
docker compose build web  # uses Dockerfile.web with standalone output
docker compose up -d web
```
Build context is `../` (SPEcosystem root) because of pnpm workspace deps.

### Rebuild Notebook Image
```bash
source .env  # needs GIT_TOKEN
docker build -t signalpilot-notebook:latest -f Dockerfile.notebook --build-arg "GIT_TOKEN=$GIT_TOKEN" .
# Import into K3s:
docker save signalpilot-notebook:latest -o /tmp/nb.tar
docker cp /tmp/nb.tar signalpilot-k3s-1:/tmp/nb.tar
docker exec signalpilot-k3s-1 ctr images import /tmp/nb.tar
```

### Run E2E Tests
```bash
cd signalpilot/web
npx playwright test e2e/hotpod-deeplink.spec.ts --project=chromium
npx playwright test e2e/cold-start.spec.ts --project=chromium
npx playwright test e2e/agent-chat.spec.ts --project=chromium
```
Note: tests use Playwright's fresh browser context (no localStorage). If a session is active in your browser, Playwright's session will conflict (SP_ALREADY_CONNECTED). Kill sessions before running tests that create new ones.

## Key Files

| File | Purpose |
|------|---------|
| `components/notebook/notebook-context.tsx` | NotebookConfig context (gateway URL, session, token, project) |
| `components/notebook/notebook-boot.tsx` | Boot sequence: health → sync → session reuse → client |
| `app/projects/page.tsx` | 3-state page: loading/no-session/ready |
| `notebook/core/network/api-call.ts` | `apiCall()` / `kernelCall()` — clean HTTP layer |
| `notebook/core/network/requests-lazy.ts` | Legacy action system for kernel ops (kept) |
| `notebook/core/edit-app.tsx` | File opening, sync-down, path resolution |
| `notebook/core/websocket/useSpKernelConnection.tsx` | Kernel WebSocket connection + auto-takeover |
| `notebook/core/websocket/useWebSocket.tsx` | Transport creation with Strict Mode fix |
| `notebook/core/runtime/runtime.ts` | RuntimeManager with markHealthy() |
| `notebook/core/kernel/session.ts` | Session ID management + setSessionId() |
| `notebook/components/editor/file-tree/state.tsx` | File tree using apiCall() directly |
| `notebook/components/editor/raw-file-editor.tsx` | Raw editor using apiCall() |
| `notebook/components/editor/dbt/dbt-panel.tsx` | dbt panel with kernel-aware detection |
| `notebook/embed/SpEmbedProviders.tsx` | Jotai store binding (handles Strict Mode) |
| `notebook/embed/initStoreOnce.ts` | Direct targetStore writes (bypasses proxy) |
| `notebook/mount.tsx` | initStore with targetStore parameter |
| `gateway/notebook_proxy/auth.py` | Token-based auth (Bearer + query param) |
| `gateway/notebook_proxy/proxy.py` | WebSocket close reason forwarding |
| `gateway/orchestrator/kubernetes.py` | Pod command with --allow-origins, faster polling |
| `gateway/main.py` | CORS headers for notebook embed |
| `middleware.ts` | CSP with ws:// origins, base-uri, img-src |
| `Dockerfile.notebook` | Optimized image (2.33GB) |
| `Dockerfile.web` | Standalone output with pnpm workspace |
| `next.config.ts` | Turbopack rules, standalone output |

## What NOT to Do
- Do NOT clear sessions without checking if the user is actively connected
- Do NOT use `require.resolve()` in next.config.ts turbopack aliases (Windows paths break)
- Do NOT add `style-mod` as a direct dep without fixing sp-notebook's node_modules
- Do NOT use the store proxy (`getRuntimeManager()`) for HTTP-only operations — use `apiCall()` instead
- Do NOT gate file operations on kernel WebSocket connection
- Do NOT use `waitForProjectSync` gates — they cause deadlocks between effects

## Next Session Priority
1. **Fix CodeMirror CSS injection** — the `style-mod` duplication must be resolved. Most promising: delete `sp-notebook/node_modules` and let workspace root handle all deps. Or use `.npmrc` with `public-hoist-pattern[]=style-mod` at workspace root.
2. **Extract shared constants** — move `GATEWAY_URL` and `IS_CLOUD_MODE` to `lib/constants.ts` and `lib/deployment-mode.ts` (15 files with duplicate declarations).
3. **Test the kernel optimizations** — forkserver + auto-instantiate + pre-warm pool are in sp-notebook but need a fresh notebook image build to take effect.
