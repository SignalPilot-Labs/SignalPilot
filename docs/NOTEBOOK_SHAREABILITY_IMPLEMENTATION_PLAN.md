# Notebook shareability and project file experience

## Working boundary

- Worktree: `/Users/lfnandoo/Projects/sagebook/SignalPilot-notebook-shareability`
- Branch: `fix/notebook-shareability`
- Base: `feature-sprint-7-22` at `0e08aa483c5cacf24e3f7d69f93837d68c1f9b20`
- Keep the original `SignalPilot` checkout untouched.

## Goal

Make a project notebook URL safe and useful to share with another authenticated
member of the same organization:

1. The recipient lands on the `/projects` workspace with the platform sidebar.
2. The recipient gets their own notebook runtime for the shared project and
   branch; no runtime session ID or pod URL is shared.
3. Ordinary Python source opens in the raw code editor, while a valid
   SignalPilot notebook opens in the cell editor.
4. Opening another file updates browser history and editor state without
   remounting the whole notebook application, re-syncing the project, or
   refreshing the document.

## Product contract for this slice

### Canonical URLs

| Purpose | URL | Contract |
| --- | --- | --- |
| Share/open in platform | `/projects?project=<id>&branch=<branch>&file=<path>` | Authenticated, same-org, platform sidebar visible |
| Explicit full-screen pop-out | `/notebook?project=<id>&branch=<branch>&file=<path>` | Authenticated, no platform sidebar |
| Runtime transport | `/notebook/<session-id>/...` | Private to the owning user; never copied or exposed as a share link |
| Legacy entry | `/notebooks?...` | Temporary 307 compatibility redirect to `/projects?...` |

The first release is **authenticated same-organization sharing**, not anonymous
or public sharing. The link follows the named branch, so it is mutable rather
than a snapshot pinned to a commit. Public links, read-only grants, immutable
snapshots, real-time co-editing, and cross-organization access are separate
product work.

### File kinds

- `notebook`: a file that the notebook server can successfully parse as a
  SignalPilot notebook and that contains notebook cells.
- `raw`: any other editable text file, including a normal `.py` module or script.
- File extension is only a fast hint. `.py` must not mean `notebook` by itself.
- A parse failure must open the file as raw text, not produce a blank notebook
  or a boot error.

### Runtime identity

A mounted editor/runtime is identified by the authenticated notebook pod plus
project and branch. The active file is navigation state inside that runtime; it
is not part of the React mount identity. Project, branch, product/trail mode, or
pod changes may reboot. A file change may not.

## Current failure chain

1. `notebook/core/active-file.ts` classifies every `.py` as `notebook`.
2. `file-explorer.tsx` opens that tab and calls `openNotebook`.
3. The embed boot path in `components/notebook/boot-runtime.ts` manually builds
   static data and bypasses the server mount-config result that already detects
   invalid/non-notebook Python and sets `rawFallback`.
4. `notebook/embed/adaptMountConfig.ts` does not carry `rawFallback` into the
   mounted editor.
5. `notebooks-page.tsx` includes `file` in `bootKey`, and `NotebookBoot` includes
   `config.file` in its boot effect dependencies. A file URL change therefore
   disposes and recreates the client, repeats health/sync/session boot work, and
   looks like a full refresh.
6. The Share button copies `window.location.href`. From the explicit
   `/notebook` pop-out this shares the no-sidebar surface instead of the
   platform workspace.
7. Cloud middleware currently treats `/notebook(.*)` as public even though the
   exact `/notebook` page needs authenticated project and session APIs.

## Implementation plan

### Phase 1 — Lock the navigation and authorization contract

- [ ] Add a single URL builder for project-backed editor links. It must accept
      `project`, `branch`, and project-relative `file`, encode each value, and
      emit a relative `/projects?...` URL.
- [ ] Change Share to copy the canonical `/projects` URL for every
      project-backed notebook, even when Share is clicked in the `/notebook`
      pop-out.
- [ ] Keep External as the only UI action that deliberately produces the
      `/notebook?...` full-screen URL. Label/tooltip it as full-screen so it is
      not confused with sharing.
- [ ] Ensure ordinary project file navigation owns only the query parameters
      and stays on the `/projects` surface. File navigation inside an explicit
      pop-out may remain on `/notebook`; its Share action must still canonicalize
      back to `/projects`.
- [ ] In cloud middleware, protect the exact `/notebook` page with Clerk just
      like `/projects`. Preserve the early rewrite for
      `/notebook/<session-id>/...`, whose gateway proxy performs its own
      per-user authorization.
- [ ] Before provisioning or reusing a project-backed notebook session, resolve
      `project_id` through `store.get_workspace_project`. Return 404 when the
      project is absent from the caller's organization. Do this before any pod
      creation or project sync.
- [ ] Preserve the existing same-user ownership checks for session lookup,
      ping, delete, and proxy access. Sharing creates/reuses the recipient's
      runtime; it never grants access to the sender's runtime.

Primary files:

- `signalpilot/web/components/notebook/notebooks-page.tsx`
- `signalpilot/web/components/notebook/notebook-boot.tsx`
- `signalpilot/web/notebook/utils/links.ts`
- `signalpilot/web/middleware.ts`
- `signalpilot/gateway/gateway/api/notebook_sessions.py`
- `signalpilot/gateway/tests/test_notebook_sessions.py`
- `signalpilot/gateway/tests/test_notebook_proxy.py`

Acceptance checks:

- Share from `/projects` and `/notebook` copies the same `/projects` link.
- The copied URL contains no notebook session ID, access token, pod host, or
  absolute local path.
- A logged-out cloud request to `/notebook?...` enters the normal sign-in flow.
- A same-org recipient can open the project through a new user-owned session.
- A different-org or missing project returns 404 without provisioning a pod.

Suggested commit:

`fix(notebooks): canonicalize authenticated project share links`

### Phase 2 — Make the server the authority on notebook versus raw Python

- [ ] Extract the existing "load as notebook or fall back to raw" logic from
      `mount_config.py` into one reusable server helper. It must return both the
      resolved safe file path and `rawFallback` without executing notebook code
      or spawning a kernel.
- [ ] Use that helper for the initial deep link and for later file selections.
      Prefer extending the existing static/file-details response over adding a
      parallel classification system.
- [ ] Return `rawFallback` in the static-data contract used by
      `bootRuntime`. For valid notebooks, retain the existing notebook/session
      snapshots; for raw files, return text content and no notebook snapshot.
- [ ] Add `rawFallback` to `NotebookStaticData` and
      `SignalpilotMountConfig`, carry it through `adaptMountConfig`, and let
      `mountOptionsSchema` initialize `rawFallbackAtom`.
- [ ] Replace `openFileInTab(path, forceRaw?)` with an explicit file-kind input.
      Do not allow `classifyFile(".py")` to override a server result.
- [ ] When a user selects an ambiguous file (`.py`, `.md`, `.qmd`), resolve its
      semantic kind before changing the active tab. Cache the result by
      project/branch/path for the mounted runtime and invalidate it after the
      file is saved or renamed.
- [ ] Keep unambiguous raw extensions on the fast local path.
- [ ] Update the WebSocket connection path so raw fallback never creates or
      reconnects a notebook kernel for that file.
- [ ] Preserve generated Slack/Notion analysis trails as notebook files and
      preserve their static session/output hydration.

Primary files:

- `signalpilot/notebook-server/signalpilot/_server/api/endpoints/mount_config.py`
- `signalpilot/notebook-server/signalpilot/_server/api/endpoints/notebook_static.py`
- `signalpilot/notebook-server/signalpilot/_server/api/endpoints/test_notebook_static.py`
- `signalpilot/notebook-server/signalpilot/_server/api/endpoints/ws/ws_session_connector.py`
- `signalpilot/web/components/notebook/boot-runtime.ts`
- `signalpilot/web/components/notebook/notebook-boot.tsx`
- `signalpilot/web/notebook/embed/types.ts`
- `signalpilot/web/notebook/embed/adaptMountConfig.ts`
- `signalpilot/web/notebook/core/active-file.ts`
- `signalpilot/web/notebook/core/file-tabs.ts`
- `signalpilot/web/notebook/core/edit-app.tsx`
- `signalpilot/web/notebook/components/editor/file-tree/file-explorer.tsx`

Server characterization tests must cover:

- valid SignalPilot `.py` -> notebook;
- normal Python module `.py` -> raw;
- syntactically invalid `.py` -> raw with original contents;
- empty `.py` -> raw;
- raw `.sql`, `.yml`, and `.md` -> raw;
- traversal/outside-workspace path -> rejection;
- generated analysis notebook -> notebook plus existing snapshots.

Suggested commits:

1. `refactor(notebook-server): centralize semantic file kind`
2. `fix(notebooks): open ordinary python files in raw editor`

### Phase 3 — Switch files without rebooting the editor

- [ ] Remove `file` from the `NotebookProvider`/`NotebookBoot` mount key.
- [ ] Treat `NotebookConfig.file` as `initialFile` after boot. Remove file-only
      changes from `NotebookBoot`'s boot effect dependencies.
- [ ] Keep one owner for in-runtime file navigation:
      `EditApp` listens for `spa:navigate` and `popstate`, resolves the file
      kind, opens/activates the tab, and reconnects WebSocket only when the new
      tab is a notebook.
- [ ] Keep one owner for URL synchronization: selecting a tab uses
      `history.pushState` for a user navigation; internal canonicalization may
      use `replaceState`. Never assign `window.location` for a same-runtime file
      change.
- [ ] Preserve browser Back/Forward behavior and prevent the current
      pushState-to-replaceState double drive.
- [ ] Reset/remount only when the runtime identity changes: pod session,
      project, branch, or product/trail mode.
- [ ] Confirm that a raw-file selection does not call `/health`,
      `/api/project/sync-down`, `/api/sessions`, or a kernel WebSocket.
- [ ] Confirm that notebook-to-notebook switching reconnects only the kernel
      WebSocket and keeps sidebar, panels, tabs, and client state mounted.
- [ ] Normalize persisted `sp:open-tabs` entries whose old extension-only type
      conflicts with the server classification.

Primary files:

- `signalpilot/web/components/notebook/notebooks-page.tsx`
- `signalpilot/web/components/notebook/notebook-boot.tsx`
- `signalpilot/web/notebook/core/edit-app.tsx`
- `signalpilot/web/notebook/core/file-tabs.ts`
- `signalpilot/web/notebook/core/router/spa-navigate.ts`

Acceptance checks:

- `document` navigation count stays at one while opening several project files.
- A file click changes the URL and selected tab without showing the outer boot
  spinner.
- Project sync occurs once per runtime/project/branch boot, not once per file.
- Sidebar and editor panel state survive every same-project file change.
- Back/Forward restores both URL and active file without creating a new pod.

Suggested commit:

`fix(notebooks): switch project files without remounting runtime`

### Phase 4 — Prove shareability with focused integration coverage

- [ ] Add `signalpilot/web/e2e/notebook-shareability.spec.ts` using a fixture
      project containing a valid notebook, an ordinary Python module, an
      invalid Python file, and a SQL file.
- [ ] Assert the platform sidebar is visible at the shared `/projects` URL.
- [ ] Assert valid notebook cells render and ordinary Python text renders in
      the raw editor.
- [ ] Instrument document navigation, boot endpoint calls, and WebSocket
      creation to prove file switching is in-place.
- [ ] Exercise Share from both surfaces and assert canonical clipboard output.
- [ ] Exercise direct deep link, click navigation, Back/Forward, reload, and
      stale `sp:open-tabs` state.
- [ ] Use two authenticated browser contexts where the cloud test harness can
      provision them:
      - user A copies the link;
      - same-org user B opens it and receives a different runtime session;
      - user B receives 404 for user A's `/notebook/<session-id>/...`;
      - different-org user C cannot resolve the project.
- [ ] If multi-user Clerk state is unavailable locally, keep the authorization
      matrix in gateway integration tests and run the two-user browser case in
      the cloud/staging job. Do not mark the feature complete until that job
      passes.

Primary files:

- `signalpilot/web/e2e/notebook-shareability.spec.ts`
- `signalpilot/web/playwright.config.ts` only if a second authenticated project
  is required
- `signalpilot/gateway/tests/test_notebook_sessions.py`
- `signalpilot/gateway/tests/test_notebook_proxy.py`
- `signalpilot/gateway/tests/test_auth_enforcement.py`

Suggested commit:

`test(notebooks): cover shared project links and in-place file switching`

## Validation commands

Run focused checks after each phase and the full build before handoff:

```bash
cd signalpilot/notebook-server
uv run --group test pytest \
  signalpilot/_server/api/endpoints/test_notebook_static.py

cd ../gateway
uv run --extra dev pytest \
  tests/test_notebook_sessions.py \
  tests/test_notebook_proxy.py \
  tests/test_auth_enforcement.py

cd ../web
pnpm exec tsc --noEmit
pnpm exec playwright test e2e/notebook-shareability.spec.ts
pnpm build
```

For the browser test, start the existing local web, gateway, database, and
notebook runtime stack first. Record any fixture project and auth prerequisites
beside the spec rather than embedding personal project IDs.

## Definition of done

- [ ] Share always produces a project-backed `/projects` URL.
- [ ] Shared links contain durable project/branch/file identity only.
- [ ] Same-org recipients use their own private runtime session.
- [ ] Exact `/notebook` UI is authenticated; session proxy behavior remains
      gateway-authorized and same-user.
- [ ] Ordinary `.py` files are visible and editable as raw text.
- [ ] Valid SignalPilot `.py` notebooks still render as cells.
- [ ] Same-runtime file switching causes no document refresh, React editor
      remount, project re-sync, or pod recreation.
- [ ] Sidebar and local editor state remain visible and stable on `/projects`.
- [ ] Generated Slack/Notion trail notebooks retain saved outputs and history.
- [ ] Focused server, gateway, browser, type, and production-build checks pass.
- [ ] Any public/read-only sharing request is tracked separately and is not
      implied by this authenticated-link release.
