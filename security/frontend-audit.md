# Frontend and Browser Security Audit

Audit date: 2026-07-29

## SP-SEC-018 - Web lock contains blocking vulnerable dependencies

**Severity: High**

`npm audit --package-lock-only --omit=dev` for `signalpilot/web` reports 14 vulnerable
packages: 2 critical, 6 high, 5 moderate, and 1 low.

The critical transitive findings are `form-data` and `request`. The repository's
audit gate temporarily risk-accepts those two packages through 2026-09-30, but it
still blocks six unaccepted high packages:

- `brace-expansion`
- `js-yaml`
- direct dependency `next`
- `postcss`
- `sharp`
- `svgo`

The current Next.js advisories include denial-of-service, source exposure, and
authorization-bypass conditions. Manual reachability review found no `"use server"`
actions, rewrites, or `next/image` usage in this app. The gateway independently
authenticates protected API calls, so a frontend middleware bypass does not by itself
authorize cloud API access. These mitigations do not justify retaining a vulnerable
framework lock.

**Remediation:** update Next.js and the direct visualization/tooling dependencies,
regenerate the lock, and run the application test suite. Remove the temporary
`form-data`/`request` exceptions by replacing or upgrading the dependency chain before
their expiry.

## SP-SEC-019 - Documentation lock contains a critical WebSocket dependency

**Severity: High**

`npm audit --package-lock-only --omit=dev` for `docs` reports 10 vulnerable packages:
1 critical, 6 high, 2 moderate, and 1 low. The critical package is
`websocket-driver`; high packages include `brace-expansion`, `fast-uri`, `js-yaml`,
`postcss`, `shell-quote`, and `svgo`.

Even when the docs site is not a production runtime, vulnerable build and preview
dependencies execute in developer and CI environments and can process untrusted
content.

**Remediation:** update the Docusaurus dependency chain and regenerate the lock.
Keep the docs lock in the same high/critical CI gate as the web lock.

## SP-SEC-020 - Content Security Policy permits broad script execution

**Severity: Low**

`signalpilot/web/middleware.ts:65-126` permits both `'unsafe-inline'` and
`'unsafe-eval'` in `script-src` and includes the configured gateway URL in
`base-uri`. The Vega stack may require eval-like behavior, but blanket inline script
permission weakens protection against markup injection. A remote gateway is not a
valid document base and does not need to be in `base-uri`.

**Remediation:** use a per-response nonce or hashes for inline scripts. Isolate the
visualization component if it must retain eval behavior. Set `base-uri 'self'` and
keep API origins in `connect-src` only. Add a browser test that verifies the emitted
CSP on authenticated and unauthenticated routes.

## SP-SEC-021 - VS Code bridge posts to any parent origin

**Severity: Low**

`signalpilot/notebook-server/core/vscode/vscode-bindings.ts:152` uses
`window.parent.postMessage(..., "*")`. No matching sensitive message receiver was
found in this revision, so no direct data leak was demonstrated.

**Remediation:** derive and validate the expected parent origin and use it as the
target origin. Validate source and origin on any future message receiver.

## Positive controls observed

- Gateway API calls from the web app attach the configured API key rather than
  relying solely on frontend middleware.
- No dangerous HTML sink was found outside the chart sanitization path.
- Chart HTML is passed through DOMPurify.
- The app does not currently contain Next.js Server Actions.
