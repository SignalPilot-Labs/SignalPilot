# Frontend Security Audit

Scope: `git diff main..HEAD` for `signalpilot/web/**` and `signalpilot/notebook-server/**` (JS/TS only), plus `plugin/**`. Backend Python and secrets scanning are out of scope. No `plugin/` files were modified in this branch.

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 0 |
| Medium | 2 |
| Low | 4 |
| Info | 3 |

Verdict: **APPROVE with hardening notes.** No exploitable frontend vulnerabilities were introduced by this branch. All new HTML-rendering paths are guarded (DOMPurify allowlist on sandbox dataframe HTML; hand-rolled Markdown for KB entries emits React children with a URL allowlist; eval transcript uses `react-markdown` with GFM only, no `rehype-raw`; no new `dangerouslySetInnerHTML` sinks). Findings below are mostly pre-existing hardening items surfaced by the changed surface, plus one supply-chain observation and one architectural note about the new client-side Anthropic API-key input.

## Findings

### [MEDIUM] Next.js downgrade in `package.json`
- File: `signalpilot/web/package.json:101,162`
- Category: dependency / supply chain
- Description: This branch downgrades `next` from `^16.2.11` to `^16.2.9` and `eslint-config-next` from `16.2.11` to `16.2.4`. Also drops the pinned `sharp: 0.35.3`/`svgo: 0.4.0.2` overrides and moves `@img/sharp-*` optionalDependencies from `0.35.3` to `0.34.5`. Downgrading a framework (especially Next.js middleware/edge, which is the CSP + Clerk auth chokepoint) is a red flag: it may reintroduce patched CVEs (Next 15.x had `CVE-2025-29927` middleware auth bypass; the 16.x line has had similar tightening in the .10/.11 patch releases). `brace-expansion` override also moved from 5.0.7 back to 5.0.6.
- Impact: If any of the Next.js patches between 16.2.9 and 16.2.11 addressed a middleware/CSP/routing security issue, this branch reopens the window. Same concern for the sharp downgrade (image processing has repeated CVE history around libvips).
- Recommendation: Justify the downgrade in the PR description and confirm no security fixes were pulled back. If the downgrade is only to work around a build issue, prefer pinning at `16.2.11` with the specific fix rather than reverting. Run `npm audit --production` and record the result in the PR.
- Confidence: medium

### [MEDIUM] Anthropic API key entered client-side and transmitted through the gateway
- File: `signalpilot/web/notebook/components/chat/agent-chat-panel.tsx:50-99`
- Category: secret handling / trust boundary
- Description: The redesigned `ApiKeySetup` now accepts an Anthropic API key (`sk-ant-...`) via a plain `<input type="password">` inside the notebook iframe and POSTs it JSON-encoded to `POST /api/agent/save-api-key`. The prior UX pushed the user to admin/integrations. Frontend concerns with the new path:
  1. The DOM value is readable by any script running in the notebook iframe (the notebook renders untrusted-shaped content — Vega specs, mermaid, HTML tables — even if today's paths sanitize, the blast radius of an XSS regression now includes the user's Anthropic key while the modal is open).
  2. The key is sent to `runtimeManager.getAgentURL("save-api-key")`, which is the gateway origin. That request rides on the same Bearer token as everything else, but there is no CSRF/anti-replay concern because Authorization headers are not sent cross-site — OK.
  3. The success handler flips `aiConfigured` state but the key value is never explicitly cleared from React state (`setApiKey(apiKey.trim())` only reads it once); the closure keeps `apiKey` alive until the component unmounts.
  4. No hint about HTTPS. In local mode this posts to `http://localhost:3300` in the clear, which is acceptable, but the user-facing copy says "Your key is stored securely on the server" — verify with the backend reviewer that `save-api-key` requires auth and stores the value only in the org's encrypted secrets store, not in a broadly-readable session log.
- Impact: Regression risk if XSS is ever introduced to the notebook host; potential accidental logging of the raw key in developer tools / error boundaries because it lives in React state.
- Recommendation: (a) Clear `apiKey` state (`setApiKey("")`) immediately after a successful save and after a failure that reveals the request body in an error message; (b) do not `String(e)` a fetch error into the UI without stripping the request body from thrown messages; (c) confirm the backend endpoint requires authentication (this reviewer did not audit `agent.py:save_api_key` for auth — flag to backend security review); (d) if IS_CLOUD_MODE, hide this UI and keep the "Ask an admin" flow — otherwise anyone with a shared browser can register a key against another user's org.
- Confidence: high (client-side observations); backend integration needs a second look from the backend reviewer

### [LOW] CSP retains `'unsafe-inline'` and `'unsafe-eval'` in `script-src`
- File: `signalpilot/web/middleware.ts:61-65`
- Category: CSP
- Description: Not introduced by this branch (pre-existing), but this branch touches `middleware.ts` and the surrounding CSP block, so it is in scope for review. Both `unsafe-inline` and `unsafe-eval` are still allowed for the entire origin because Next.js hydration and Vega both need them. The rationale is documented inline, which is good.
- Impact: XSS mitigations via CSP are limited to the `object-src 'none'`, `frame-ancestors 'none'`, and `default-src 'self'` fallbacks. An injected `<script>` can execute.
- Recommendation: Long-term, migrate to a nonce-based CSP (Next.js 15+ supports `<Script nonce>`) and isolate Vega into an iframe/worker so `unsafe-eval` can be dropped. Not blocking this PR.
- Confidence: high

### [LOW] `base-uri` includes the gateway origin
- File: `signalpilot/web/middleware.ts:125`
- Category: CSP
- Description: `base-uri 'self' ${gatewayUrl}`. Allowing an untrusted-if-compromised gateway to become the base URI would let a stored `<base>` tag from HTML output rewrite all relative URLs. The sandbox page renders HTML through DOMPurify with `<base>` implicitly forbidden (not in `ALLOWED_TAGS`), so today this is fine. But `base-uri` typically should be `'self'` only.
- Impact: Defense-in-depth erosion if any HTML sink ever allows `<base>` or if an attacker injects a `<base>` via non-CSP-protected route.
- Recommendation: Change to `base-uri 'self'`. The gateway does not need to be a `base-uri` target.
- Confidence: high

### [LOW] `postMessage` targets `"*"` in vscode-bindings.ts (unchanged, but adjacent to embed refactor)
- File: `signalpilot/web/notebook/core/vscode/vscode-bindings.ts:152`
- Category: postMessage
- Description: `sendToPanelManager()` calls `window.parent?.postMessage(msg, "*")` — targets any origin — and the `message` listener on line 53 accepts any `event.data` without verifying `event.origin` or `event.source`. Only activated when `?vscode` query param is present AND the page is embedded. Not modified by this branch, but the embed harness (`SpEmbedProviders`, `mount.tsx`) was heavily restructured, so re-evaluated. Data sent is limited to selection text / clipboard content — an eavesdropping parent can steal clipboard-adjacent data. The paste-from-parent path calls `document.execCommand("insertText", false, message.text)` with attacker-controlled text if `?vscode` is on.
- Impact: If a page is embedded with `?vscode`, any parent frame can inject arbitrary text into the active input by posting `{command: "paste", text: "..."}`, and can read every text selection the user makes. `frame-ancestors 'none'` in CSP is the primary mitigation; this only affects intentional VS Code webview integration.
- Recommendation: Restrict `postMessage` target to a validated origin (the VS Code webview host injects `acquireVsCodeApi().postMessage`, but if you continue to use raw `postMessage`, target the specific parent origin discovered at bind time). Filter the `message` listener with `event.origin` / `event.source === window.parent`. Add a shape validator on `message.command` and `message.text`.
- Confidence: high

### [LOW] `parse-check.mjs` reads env-derived path and passes it to `fs.readFileSync`
- File: `signalpilot/web/parse-check.mjs:3`
- Category: input handling (dev/diagnostic script)
- Description: `fs.readFileSync(process.env.TEMP + "/transcript.txt", "utf8")` — dev-only diagnostic script for the eval transcript parser. Not shipped to the browser, not on any code path. Flagged only because it's a new file introduced in this branch.
- Impact: None in the browser bundle. If accidentally imported into a route, would fail at build (Node fs). Path traversal is not exploitable since `TEMP` is a local env var.
- Recommendation: Move to `signalpilot/web/scripts/` or `tools/` and add a header comment explaining it is not part of the app.
- Confidence: high

### [INFO] Sandbox dataframe HTML sink is properly sanitized
- File: `signalpilot/web/app/sandboxes/[id]/page.tsx:499`, sanitizer at `:44-52`
- Category: XSS
- Description: `dangerouslySetInnerHTML={{ __html: entry.htmlContent }}` is fed only by `sanitizeTableHtml()`, which calls `DOMPurify.sanitize(html, { ALLOWED_TAGS: [table, thead, tbody, ..., pre, code], ALLOWED_ATTR: [colspan, rowspan, class, scope], FORBID_ATTR: [style, id, onclick, onerror, onload, onmouseover] })`. Strict allowlist; no `<a>`, no `<img>`, no `<script>`, no event handlers, no `<style>`. Regex extraction of `<table>...</table>` from output before sanitization is fine — DOMPurify is the actual boundary. Approved.
- Confidence: high

### [INFO] KB DocumentView markdown renderer is safe by construction
- File: `signalpilot/web/app/knowledge/_components/DocumentView.tsx`
- Category: XSS
- Description: Custom markdown renderer emits React children (never `dangerouslySetInnerHTML`). Link handling explicitly checks `SAFE_URL = /^https?:\/\//` before rendering `<a href={m[2]} target="_blank" rel="noopener noreferrer">`. Wikilinks `[[…]]` are resolved against the local doc list and rendered as `<button>` with `onNavigate(resolved.id)` — the anchor never receives untrusted href. Approved. Note that the comment "SAFE_URL anchors the external-link allowlist. DO NOT broaden to javascript:/data:/etc." is well placed — keep it.
- Confidence: high

### [INFO] Eval transcript / chats reader uses `react-markdown` without `rehype-raw`
- File: `signalpilot/web/app/evals/_components/Markdown.tsx`, `turns.tsx`, `app/chats/page.tsx`
- Category: XSS
- Description: `<ReactMarkdown remarkPlugins={[remarkGfm]}>` with no `rehype-raw`/`rehype-html` — raw HTML in the source is escaped by default. Tool inputs/results are rendered as text or in `<pre>` blocks. The transcript is populated from `parseTranscript(raw)` which `JSON.parse`s line-delimited events and passes only strings into `<Md>`. Approved.
- Confidence: high

## Areas reviewed clean

- `signalpilot/web/notebook/embed/` (SpEmbedProviders, createSignalpilotClient, SignalpilotEditor, SignalpilotHome, initStoreOnce, mount.tsx): refactor moves registry creation eager rather than lazy and inlines the SpApp import. No new `postMessage`, iframe, `eval`, or dangerous DOM sinks introduced. `mount.tsx` inlines a Zod schema for mount options — parses/validates external `options`, no `passthrough` shortcut for auth-relevant fields, and `authToken` accepts only `string | function | null` via a `z.custom` predicate.
- `signalpilot/web/notebook/components/editor/Output.tsx` + deleted `VegaOutput.tsx`: pure code-motion (LazyVegaOutput inlined into OutputRenderer). No new sinks; Vega still uses canvas renderer.
- `signalpilot/web/notebook/core/runtime/runtime.ts`: only adds `"save-api-key"` to the allowed path union. No runtime code exec change.
- `signalpilot/web/lib/api.ts`: new multipart-upload path uses `XMLHttpRequest.open("PUT", url)` where `url` comes from the trusted gateway `initiate` response (part_urls). Auth model (Bearer from Clerk or sessionStorage local key) is unchanged and consistent. `sessionStorage` migration from `localStorage` is the correct direction for reducing XSS blast radius.
- `signalpilot/web/app/chats/page.tsx`, `evals/upload/page.tsx`, `demo-db/page.tsx`, `knowledge/*`, `sandboxes/*` (styling), `settings/*`, `evals/_components/TranscriptView.tsx`, `turns.tsx`: no `innerHTML`, no `dangerouslySetInnerHTML`, no `eval`, no dynamic `href` from untrusted values, no new `postMessage`, no `NEXT_PUBLIC_*` secrets leaked. Only trusted env vars shipped to the bundle (gateway URL, backend URL, deployment mode, Clerk publishable key, MCP URL, eval S3 origin, version, sp version) — all appropriate for public disclosure.
- `signalpilot/web/middleware.ts`: adds S3 upload origin to `connect-src` behind `isSafeUrl()`. Correctly gated by http/https protocol check. `X-Frame-Options: DENY` and `frame-ancestors 'none'` retained — clickjacking mitigated. HSTS conditional on `x-forwarded-proto === https` — fine.
- `signalpilot/web/e2e/agent-chat.spec.ts`, `e2e-*.mjs`: e2e/dev only, no shipped code.
- No hardcoded `sk-`, `sk-ant-`, Anthropic/Xata/OpenAI/AWS keys, DSNs, or Clerk secret keys found in the diff. `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is (correctly) a publishable key.
