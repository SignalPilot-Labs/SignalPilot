# Marimo References Audit

All references to "marimo" (case-insensitive) in source files, file names, and directory names.
Excludes `.git/`, `node_modules/`, `.next/`, `.turbo/`, `dist/`, `build/`.

---

## Directory / File Names

- [ ] `signalpilot/web/public/marimo/` — entire directory (static assets: `site.webmanifest`, `files/wasm-intro.py`, `assets/*.js`)

---

## Documentation / Agent Guides

- [ ] `agent-notebooks.md:3` — "a fork of marimo. **Never reference marimo**"
- [ ] `agent-notebooks.md:87` — `never "import marimo"`
- [ ] `agent-notebooks.md:90` — "Every `mo.` in marimo docs becomes `sp.`"
- [ ] `agent-notebooks.md:186` — "never `import marimo`"

---

## E2E / Integration Tests

- [ ] `test_notebook_e2e.py:89` — comment: "Wait for iframe + marimo render"
- [ ] `test_notebook_e2e.py:90` — `print("[2] Waiting for marimo to load...")`
- [ ] `test_notebook_e2e.py:111` — `print(f"    marimo rendered after ...")`
- [ ] `test_notebook_e2e.py:115` — `fail("marimo did not render", ...)`
- [ ] `test_notebook_e2e.py:117` — screenshot name `e2e_02_marimo_home.png`
- [ ] `test_notebook_e2e.py:276` — `print(f"  marimo rendered:      YES")`
- [ ] `test_cloud_notebook.py:105` — `iframe[title='Marimo notebook']`
- [ ] `test_cloud_notebook.py:118` — `iframe[title='Marimo notebook']`

---

## Gateway — Kubernetes / Orchestrator

- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:72` — comment: "tells marimo to emit asset URLs"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:79` — comment: "MARIMO_LOG_DIR"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:98` — comment: "marimo is installed at /opt/sp-notebook"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:103` — env var `MARIMO_LOG_DIR` = `/tmp/marimo-logs`
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:145` — comment: "before starting marimo"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:146` — comment: "before marimo opens /workspace"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:148` — comment: "marimo HTTP port"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:151` — comment: "without marimo's built-in auth"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:153` — comment: "tells marimo to emit asset/WS URLs"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:466` — comment: "after marimo starts"
- [ ] `signalpilot/gateway/gateway/orchestrator/kubernetes.py:502` — comment: "starts marimo only after"

---

## Gateway — Notebook Proxy

- [ ] `signalpilot/gateway/gateway/notebook_proxy/routes.py:162` — comment: "marimo emits under --base-url"
- [ ] `signalpilot/gateway/gateway/notebook_proxy/routes.py:176` — comment: "marimo session-ID abuse"
- [ ] `signalpilot/gateway/gateway/notebook_proxy/proxy.py:9` — comment: "marimo's session cookie"
- [ ] `signalpilot/gateway/gateway/notebook_proxy/constants.py:15` — comment: "Internal port marimo pods listen on"
- [ ] `signalpilot/gateway/gateway/notebook_proxy/constants.py:58` — comment: "prevent marimo's own session cookie"

---

## Gateway — MCP / API / Middleware

- [ ] `signalpilot/gateway/gateway/mcp/tools/notebook.py:1` — docstring: "execute a marimo notebook"
- [ ] `signalpilot/gateway/gateway/mcp/tools/notebook.py:22` — docstring: "Run a marimo .py notebook"
- [ ] `signalpilot/gateway/gateway/api/notebook_sessions.py:150` — comment: "wait for readinessProbe (marimo binds port)"
- [ ] `signalpilot/gateway/gateway/http/middleware/security_headers.py:7` — comment: "marimo's own HTML/JS"
- [ ] `signalpilot/gateway/gateway/http/middleware/security_headers.py:11` — comment: "let marimo's own caching headers pass"
- [ ] `signalpilot/gateway/gateway/http/middleware/security_headers.py:62` — comment: "so marimo works"

---

## Gateway — Tests

- [ ] `signalpilot/gateway/tests/test_pod_security_context.py:6` — comment: "MARIMO_LOG_DIR"
- [ ] `signalpilot/gateway/tests/test_pod_security_context.py:88` — test name: `test_pod_env_has_marimo_log_dir_in_tmp`
- [ ] `signalpilot/gateway/tests/test_pod_security_context.py:89` — docstring: "MARIMO_LOG_DIR"
- [ ] `signalpilot/gateway/tests/test_pod_security_context.py:93` — assert `"MARIMO_LOG_DIR" in env_dict`
- [ ] `signalpilot/gateway/tests/test_pod_security_context.py:94` — assert `env_dict["MARIMO_LOG_DIR"]`
- [ ] `signalpilot/gateway/tests/test_notebook_proxy.py:511` — `"marimo_session=secret123"`

---

## Deploy

- [ ] `signalpilot/deploy/k8s/README.md:16` — "before marimo starts"

---

## Web — package.json (npm dependencies)

- [ ] `signalpilot/web/package.json:45` — `@marimo-team/codemirror-languageserver`
- [ ] `signalpilot/web/package.json:46` — `@marimo-team/codemirror-mcp`
- [ ] `signalpilot/web/package.json:47` — `@marimo-team/codemirror-sql`
- [ ] `signalpilot/web/package.json:48` — `@marimo-team/react-slotz`

---

## Web — Next.js Pages

- [ ] `signalpilot/web/app/notebook-test/page.tsx:16` — `src="/marimo/index.html"`

---

## Web — Public Static Assets

- [ ] `signalpilot/web/public/marimo/site.webmanifest:16` — `"name": "marimo"`
- [ ] `signalpilot/web/public/marimo/site.webmanifest:17` — `"short_name": "marimo"`
- [ ] `signalpilot/web/public/marimo/files/wasm-intro.py` — 40+ references to "marimo" throughout the tutorial text (lines 11, 19, 43, 83, 85, 101, 104, 105, 123, 129, 156, 171, 219, 220, 260, 262, 266, 285, 289, 299, 307, 315, 324, 331, 333, 337, 339, 340, 341, 351, 387, 406, 446)
- [ ] `signalpilot/web/public/marimo/assets/*.js` — minified build bundles (30+ files with embedded references)

---

## Notebook — Utils

- [ ] `notebook/utils/traceback.ts:19` — comment: "contains a marimo cell file"
- [ ] `notebook/utils/traceback.ts:21` — function name: `elementContainsMarimoCellFile`
- [ ] `notebook/utils/traceback.ts:47` — comment: `/tmp/marimo_<number>/`
- [ ] `notebook/utils/traceback.ts:75` — comment: `/tmp/marimo_<number>/`
- [ ] `notebook/utils/traceback.ts:80` — comment: `marimo://notebook#cell`
- [ ] `notebook/utils/semaphore.ts:71` — lint directive: `marimo/prefer-object-params`
- [ ] `notebook/utils/Logger.ts:63` — namespace prefix: `marimo:`
- [ ] `notebook/utils/events.ts:43` — tag check: `tagName.startsWith("MARIMO")`

---

## Notebook — Core: Config

- [ ] `notebook/core/config/config.ts:20` — atom name: `resolvedMarimoConfigAtom`
- [ ] `notebook/core/config/config.ts:27,31,43,47,51,55` — reads from `resolvedMarimoConfigAtom`
- [ ] `notebook/core/config/config.ts:65` — function: `useResolvedMarimoConfig`
- [ ] `notebook/core/config/config.ts:72` — function: `getResolvedMarimoConfig`
- [ ] `notebook/core/config/config.ts:77,81,85,119` — reads `resolvedMarimoConfigAtom`
- [ ] `notebook/core/config/config-schema.ts:221,239,243,262` — error messages: "Marimo got an unexpected value"
- [ ] `notebook/core/config/feature-flag.tsx:3` — import: `getResolvedMarimoConfig`
- [ ] `notebook/core/config/feature-flag.tsx:25` — calls `getResolvedMarimoConfig()`

---

## Notebook — Core: Static State

- [ ] `notebook/core/static/static-state.ts:25` — function: `isMarimoStaticState`
- [ ] `notebook/core/static/static-state.ts:44` — function: `getMarimoStaticState`
- [ ] `notebook/core/static/static-state.ts:50,54,58,64` — calls `isMarimoStaticState`/`getMarimoStaticState`
- [ ] `notebook/core/static/export-context.ts:17` — function: `isMarimoExportContext`
- [ ] `notebook/core/static/export-context.ts:37` — function: `getMarimoExportContext`
- [ ] `notebook/core/static/export-context.ts:41,45` — calls `isMarimoExportContext`/`getMarimoExportContext`
- [ ] `notebook/core/static/export-context.ts:58` — comment: "served by marimo as an app"

---

## Notebook — Core: Network / API

- [ ] `notebook/core/network/api.ts:1` — import: `createMarimoClient`
- [ ] `notebook/core/network/api.ts:193` — variable: `const spClient = createMarimoClient`

---

## Notebook — Core: WebSocket

- [ ] `notebook/core/websocket/useSpKernelConnection.tsx:125` — error message: "please file a bug with marimo"
- [ ] `notebook/core/websocket/useSpKernelConnection.tsx:177` — comment: "connection to the Marimo kernel"

---

## Notebook — Core: CodeMirror

- [ ] `notebook/core/codemirror/replace-editor-content.ts:3` — import from `@marimo-team/codemirror-languageserver`
- [ ] `notebook/core/codemirror/misc/paste.ts:28` — comment: "cells from a marimo app"
- [ ] `notebook/core/codemirror/misc/paste.ts:31` — comment: "looks like a marimo app"
- [ ] `notebook/core/codemirror/lsp/utils.ts:24` — URI: `file:///__marimo_notebook__.py`
- [ ] `notebook/core/codemirror/lsp/types.ts:1` — import from `@marimo-team/codemirror-languageserver`
- [ ] `notebook/core/codemirror/lsp/transports.ts:8` — comment: "connected to the marimo runtime"
- [ ] `notebook/core/codemirror/lsp/notebook-lsp.ts:27` — comment: "Private variables in marimo"
- [ ] `notebook/core/codemirror/lsp/notebook-lsp.ts:535` — comment: "Private variables in marimo"
- [ ] `notebook/core/codemirror/language/languages/sql/utils.ts:16` — import from `@marimo-team/codemirror-sql/dialects`
- [ ] `notebook/core/codemirror/language/languages/sql/sql.ts:19,20` — imports from `@marimo-team/codemirror-sql`
- [ ] `notebook/core/codemirror/language/languages/sql/sql-mode.ts:6` — storage key: `marimo:notebook-sql-mode`
- [ ] `notebook/core/codemirror/language/languages/sql/completion-sources.tsx:7,93,96` — imports from `@marimo-team/codemirror-sql`
- [ ] `notebook/core/codemirror/language/languages/sql/banner-validation-errors.ts:1` — import from `@marimo-team/codemirror-sql`
- [ ] `notebook/core/codemirror/language/languages/python.ts:17` — import from `@marimo-team/codemirror-languageserver`
- [ ] `notebook/core/codemirror/language/languages/python.ts:71` — comment: "not useful in marimo"
- [ ] `notebook/core/codemirror/language/languages/python.ts:85` — config key: `marimo_plugin`
- [ ] `notebook/core/codemirror/keymaps/vim.ts:9,132` — import/use `resolvedMarimoConfigAtom`
- [ ] `notebook/core/codemirror/format.ts:11,28,37` — import/use `getResolvedMarimoConfig`; comment: "via the marimo server"
- [ ] `notebook/core/codemirror/completion/keymap.ts:12,16` — GitHub issue URLs: `sp-team/marimo`
- [ ] `notebook/core/codemirror/completion/accept-on-enter-atom.ts:5` — storage key: `marimo:accept-completion-on-enter`
- [ ] `notebook/core/codemirror/compat/jupyter.tsx:186` — message: "Magic commands are not supported in marimo"
- [ ] `notebook/core/codemirror/cells/extensions.ts:280` — GitHub issue URL: `sp-team/marimo`
- [ ] `notebook/core/codemirror/cells/traceback-decorations.ts:108` — event name: `marimo.error-decoration-update`

---

## Notebook — Core: Other

- [ ] `notebook/core/cells/add-missing-import.ts:55` — comment: "Adds a marimo import"
- [ ] `notebook/core/cells/cell.ts:79` — comment: "marimo includes an error output"
- [ ] `notebook/core/cells/types.ts:104` — comment: "whether marimo encountered an error"
- [ ] `notebook/core/cells/scrollCellIntoView.ts:47` — GitHub issue URL: `sp-team/marimo`
- [ ] `notebook/core/datasets/engines.ts:8` — constant: `DUCKDB_ENGINE = "__marimo_duckdb"`
- [ ] `notebook/core/dom/ui-element.ts:1` — import: `isCustomMarimoElement`
- [ ] `notebook/core/dom/ui-element.ts:72,150,179,208` — comments/calls referencing "marimo" elements
- [ ] `notebook/core/dom/events.ts:54,72` — comments: "tell marimo that a value has changed"
- [ ] `notebook/core/meta/code-visibility.ts:10` — comment: "In `marimo run`"
- [ ] `notebook/core/runtime/runtime.ts:337` — comment: "prefix with `marimo`"
- [ ] `notebook/core/slots/slots.ts:1` — import from `@marimo-team/react-slotz`
- [ ] `notebook/core/SpApp.tsx:5,10,59,62` — import `@marimo-team/react-slotz`; import/use `useResolvedMarimoConfig`; comment: "root component of the Marimo app"

---

## Notebook — Plugins

- [ ] `notebook/plugins/core/trusted-url.ts:15` — comment: "marimo custom elements"
- [ ] `notebook/plugins/core/sanitize-html.ts:48` — regex: `/^(marimo-[A-Za-z][\w-]*|iconify-icon)$/`
- [ ] `notebook/plugins/core/RenderHTML.tsx:217` — comment: "Marimo custom elements"
- [ ] `notebook/plugins/core/RenderHTML.tsx:227` — check: `tagName.startsWith("marimo-")`
- [ ] `notebook/plugins/core/registerReactComponent.tsx:7` — comment: "to and from the rest of marimo"
- [ ] `notebook/plugins/core/registerReactComponent.tsx:71` — interface: `IMarimoHTMLElement`
- [ ] `notebook/plugins/core/registerReactComponent.tsx:276` — constant: `__custom_marimo_element__`
- [ ] `notebook/plugins/core/registerReactComponent.tsx:322,326,363-365,373,375,378,580` — comments/methods: `isLightDOMChildOfMarimoElement`, marimo element handling
- [ ] `notebook/plugins/core/registerReactComponent.tsx:611,613` — function: `isCustomMarimoElement`, type guard `IMarimoHTMLElement`
- [ ] `notebook/plugins/impl/anywidget/widget-binding.ts:16` — error message: "not supported in marimo"
- [ ] `notebook/plugins/impl/anywidget/widget-binding.ts:84,87` — comments: "marimo virtual file paths", "marimo-*"
- [ ] `notebook/plugins/impl/anywidget/model.ts:125,128,170-173,356,406,426` — function: `getMarimoInternal`; comments: "Internal marimo API"
- [ ] `notebook/plugins/impl/plotly/usePlotlyLayout.ts:44` — GitHub issue URL: `sp-team/marimo`
- [ ] `notebook/plugins/impl/plotly/plotly-component.tsx:68` — comment: "Serve this library from Marimo"
- [ ] `notebook/plugins/impl/NumberPlugin.tsx:80` — GitHub issue URL: `sp-team/marimo`
- [ ] `notebook/plugins/impl/DataTablePlugin.tsx:1` — import from `@marimo-team/react-slotz`
- [ ] `notebook/plugins/impl/DataTablePlugin.tsx:588` — GitHub issue URL: `sp-team/marimo`
- [ ] `notebook/plugins/impl/DataTablePlugin.tsx:991` — comment: "maps to the _value in marimo/"
- [ ] `notebook/plugins/impl/data-frames/panel.tsx:368` — GitHub issue URL: `sp-team/marimo`

---

## Notebook — Components

- [ ] `notebook/components/app-config/optional-features.tsx:15,104` — import/use `useResolvedMarimoConfig`
- [ ] `notebook/components/datasources/utils.ts:1` — import from `@marimo-team/codemirror-sql/dialects`
- [ ] `notebook/components/slides/swiper-component.tsx:111,114` — check: `startsWith("marimo-")`
- [ ] `notebook/components/slides/reveal-slides.css:3,22,28` — comments: "marimo's defaults", "marimo's font", "marimo's primary color"
- [ ] `notebook/components/scratchpad/scratchpad.tsx:19,52` — import/use `useResolvedMarimoConfig`
- [ ] `notebook/components/scratchpad/scratchpad-history.ts:6` — storage key: `marimo:scratchpadHistory:v1`
- [ ] `notebook/components/home/state.ts:31,37` — storage keys: `marimo:home:include-markdown`, `marimo:home:expanded-folders`
- [ ] `notebook/components/editor/renderers/vertical-layout/vertical-layout.tsx:31,68` — import/use `useResolvedMarimoConfig`
- [ ] `notebook/components/editor/renderers/vertical-layout/sidebar/wrapped-with-sidebar.tsx:1` — import from `@marimo-team/react-slotz`
- [ ] `notebook/components/editor/renderers/vertical-layout/sidebar/sidebar-slot.tsx:1` — import from `@marimo-team/react-slotz`
- [ ] `notebook/components/editor/renderers/slides-layout/types.ts:12` — comment: "earlier marimo versions"
- [ ] `notebook/components/editor/renderers/slides-layout/plugin.tsx:22` — comment: "older marimo versions"
- [ ] `notebook/components/editor/renderers/grid-layout/grid-layout.tsx:164` — GitHub issue URL: `sp-team/marimo`
- [ ] `notebook/components/editor/RecoveryButton.tsx:40` — `marimo_version: getSpVersion()`
- [ ] `notebook/components/editor/RecoveryButton.tsx:94` — UI text: `marimo recover`
- [ ] `notebook/components/editor/package-alert.tsx:30,95,205,379` — import/use `useResolvedMarimoConfig`; UI text: "marimo can install these packages"
- [ ] `notebook/components/editor/Output.tsx:220` — message: "not supported in marimo"
- [ ] `notebook/components/editor/output/useWrapText.ts:5` — storage key: `marimo:console:wrapText`
- [ ] `notebook/components/editor/output/SpTracebackOutput.tsx:36,51,229` — import/use `elementContainsMarimoCellFile`; comment: "Marimo semantics"
- [ ] `notebook/components/editor/output/SpErrorOutput.tsx:54,284,331,442` — comments/UI text: "Marimo semantics", "marimo to know", "marimo requires", "The marimo module"
- [ ] `notebook/components/editor/output/JsonOutput.tsx:134,385` — comments: `marimo/_output/formatters`
- [ ] `notebook/components/editor/navigation/navigation.ts:7` — import from `@marimo-team/codemirror-languageserver`
- [ ] `notebook/components/editor/links/cell-link.tsx:85` — URI scheme: `marimo://`
- [ ] `notebook/components/editor/header/filename-input.tsx:219` — comment: `marimo/_utils/marimo_path.py`
- [ ] `notebook/components/editor/file-tree/file-explorer.tsx:91` — storage key: `marimo:showHiddenFiles`
- [ ] `notebook/components/editor/file-tree/file-explorer.tsx:231,266-273,424-494,590,706,763` — functions: `openMarimoNotebook`, `handleOpenMarimoFile`, `onOpenMarimoFile`
- [ ] `notebook/components/editor/errors/fix-mode.ts:7` — storage key: `marimo:ai-autofix-mode`
- [ ] `notebook/components/editor/dynamic-favicon.tsx:76` — comment: "default marimo favicon"
- [ ] `notebook/components/editor/controls/keyboard-shortcuts.tsx:8,39` — import/use `useResolvedMarimoConfig`
- [ ] `notebook/components/editor/columns/storage.ts:5` — storage key: `marimo:notebook-col-sizes`
- [ ] `notebook/components/editor/chrome/wrapper/footer-items/runtime-settings.tsx:21,35` — import/use `useResolvedMarimoConfig`
- [ ] `notebook/components/editor/chrome/wrapper/footer-items/machine-stats.tsx:88` — UI text: "marimo server:"
- [ ] `notebook/components/editor/chrome/panels/packages-panel.tsx:22,68` — import/use `useResolvedMarimoConfig`
- [ ] `notebook/components/editor/chrome/panels/context-aware-panel/context-aware-panel.tsx:1` — import from `@marimo-team/react-slotz`
- [ ] `notebook/components/editor/cell/CreateCellButton.tsx:58` — comment: "adding the marimo import"
- [ ] `notebook/components/editor/actions/useNotebookActions.tsx:53,107,613,626` — import/use `useResolvedMarimoConfig`; comments: "ran `marimo edit`"
- [ ] `notebook/components/editor/actions/useConfigActions.tsx:1,8` — import/use `useResolvedMarimoConfig`
- [ ] `notebook/components/dependency-graph/elements.ts:156` — comment: "Skip marimo"
- [ ] `notebook/components/data-table/range-focus/use-cell-range-selection.ts:134-166` — constant: `CONTENT_WRAPPER_MARIMO_TAGS`; GitHub issue URL
- [ ] `notebook/components/data-table/cell-selection/feature.ts:69` — GitHub issue URL: `sp-team/marimo`
- [ ] `notebook/components/data-table/table-explorer-panel/table-explorer-panel.tsx:1` — import from `@marimo-team/react-slotz`

---

## Notebook — Embed / Mount / Theme / Hooks / CSS

- [ ] `notebook/mount.tsx:75,77,197,201,248,266,270,274` — comments/logs: "marimo app", "[marimo] received JSON", "marimo version", "marimo config"
- [ ] `notebook/embed/types.ts:21,91` — comments: "Marimo-Server-Token", "default marimo theme"
- [ ] `notebook/theme/useTheme.ts:2,11` — import/use `resolvedMarimoConfigAtom`
- [ ] `notebook/hooks/useRecentCommands.ts:9` — storage key: `marimo:commands`
- [ ] `notebook/css/progress.css:5` — comment: "marimo native components"
- [ ] `notebook/css/md.css:120` — GitHub issue URL: `sp-team/marimo`
- [ ] `notebook/css/globals.css:85` — comment: "marimo-style depth"

---

## Summary by Category

| Category | Count |
|----------|-------|
| Comments / docstrings | ~90 |
| Function / variable / type names | ~25 |
| Storage keys (`marimo:*`) | 8 |
| `@marimo-team/*` npm imports | 4 packages, ~15 import sites |
| GitHub issue URLs (`sp-team/marimo`) | ~12 |
| UI-facing text shown to users | ~8 |
| Env vars / constants (`MARIMO_*`, `__marimo_*`) | 4 |
| File/directory names | 1 (`public/marimo/`) |
| Static assets (minified JS bundles) | 30+ files in `public/marimo/assets/` |
