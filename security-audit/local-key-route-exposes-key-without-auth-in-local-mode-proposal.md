# `/api/local-key` returns the local API key to anyone reaching the dev server

- Slug: local-key-route-exposes-key-without-auth-in-local-mode
- Severity: Low
- Cloud impact: Partial
- Confidence: High
- Affected files / endpoints: `signalpilot/web/app/api/local-key/route.ts:1-14`

Back to [issues.md](issues.md)

---

## Problem

The `/api/local-key` route returns `process.env.SP_LOCAL_API_KEY` to any caller with no authentication and no cloud-mode guard:

```typescript
// app/api/local-key/route.ts:1-14
export async function GET() {
  const key = process.env.SP_LOCAL_API_KEY;
  if (!key) {
    return NextResponse.json({ key: null });
  }
  return NextResponse.json({ key });
}
```

In normal local mode, `SP_LOCAL_API_KEY` is set from a shared volume (written by the gateway at startup). The route is accessed by the frontend's `_fetchLocalKey()` function to auto-configure the API key.

Problems:
1. **No cloud-mode guard.** In a misconfigured cloud deploy where `SP_LOCAL_API_KEY` is accidentally set (e.g., copied from a local `.env`), this endpoint returns the value to any unauthenticated caller — including external attackers who discover the endpoint.
2. **No `same-origin` check.** The route is a server-side route, but any script or cross-origin request can call it. The same-origin policy protects cookies but not API routes.
3. **Implicit trust in network access.** If the Next.js app is ever exposed without authentication (e.g., during development on a corporate network), any device on the network can retrieve the local API key.

---

## Impact

- **Cloud (misconfigured):** If `SP_LOCAL_API_KEY` is set in cloud mode, any unauthenticated attacker who finds the endpoint retrieves the key and gets full gateway access.
- **Local (developer machine on shared network):** Any device on the same network can retrieve the developer's local API key and issue queries to their gateway.
- In practice, cloud deployments should not have `SP_LOCAL_API_KEY` set — but the lack of a guard means there is no enforcement.

---

## Exploit scenario

```bash
# Attacker on same network as developer:
curl http://developer-laptop:3200/api/local-key
# Returns: {"key": "sp_local_abc123..."}

# Attacker uses key:
curl http://developer-laptop:3300/api/connections \
  -H "X-API-Key: sp_local_abc123..."
# Returns all developer's connections
```

**Cloud misconfiguration scenario:**
```bash
# .env accidentally copied to cloud deploy with SP_LOCAL_API_KEY set:
curl https://signalpilot.ai/api/local-key
# Returns: {"key": "sp_local_abc123..."} — exposed to internet
```

---

## Affected surface

- Files: `signalpilot/web/app/api/local-key/route.ts:1-14`
- Endpoints: `GET /api/local-key`
- Auth modes: Unauthenticated; local mode by design, cloud mode by accident

---

## Proposed fix

Add a cloud-mode guard and document the endpoint clearly:

```typescript
// app/api/local-key/route.ts:
import { NextResponse } from "next/server";
import { headers } from "next/headers";

export async function GET(request: Request) {
  // Guard: never return key in cloud mode
  if (process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud") {
    return NextResponse.json(
      { error: "Not available in cloud mode" },
      { status: 404 }
    );
  }

  // Guard: only accept same-origin requests (check Referer/Origin header)
  const origin = request.headers.get("origin");
  const appUrl = process.env.NEXTAUTH_URL || "http://localhost:3200";
  if (origin && origin !== appUrl) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const key = process.env.SP_LOCAL_API_KEY;
  if (!key) {
    return NextResponse.json({ key: null });
  }
  return NextResponse.json({ key });
}
```

Additionally, in `docker-compose.yml`, ensure `SP_LOCAL_API_KEY` is only present for the local stack and is removed from any cloud-mode environment files.

---

## Verification / test plan

**Unit tests:**
1. `test_local_key_cloud_mode_returns_404` — set `NEXT_PUBLIC_DEPLOYMENT_MODE=cloud`, GET request, assert 404.
2. `test_local_key_cross_origin_returns_403` — request with different origin header, assert 403.
3. `test_local_key_same_origin_returns_key` — local mode, same origin, assert key returned.

**Manual checklist:**
- Set `NEXT_PUBLIC_DEPLOYMENT_MODE=cloud` in Next.js env.
- Call `/api/local-key`.
- Expect 404, not key.

---

## Rollout / migration notes

- No breaking change for local-mode users (same-origin check is satisfied by browser requests).
- Cloud deployments unaffected (404 returned before key is read).
- Rollback: remove the guards.
