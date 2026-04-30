# CSP `connect-src` is computed from env vars at build time; any misconfiguration becomes browser-trusted

- Slug: csp-connect-src-includes-arbitrary-backend-url
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/web/middleware.ts:47-49`

Back to [issues.md](issues.md)

---

## Problem

The `connect-src` directive in the CSP is built from the `NEXT_PUBLIC_BACKEND_URL` environment variable without validation:

```typescript
// middleware.ts:47-49
const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
connectSrc += ` ${backendUrl}`;
```

If `NEXT_PUBLIC_BACKEND_URL` is set to an attacker-controlled domain (through a CI/CD misconfiguration, a compromised secrets store, or a supply-chain attack on the build pipeline), the browser will allow `fetch()` requests to that domain with credentials. Since `allow_credentials=True` is set in the CORS config and browsers send cookies/auth headers to CSP-whitelisted origins, this becomes a CSRF vector.

Additionally, there is no validation that `backendUrl` is HTTPS in cloud mode. A `http://` URL in `connect-src` in cloud mode means the browser allows sending credentials to an unencrypted endpoint.

---

## Impact

- Compromised `NEXT_PUBLIC_BACKEND_URL` in CI/CD → attacker's server whitelisted in CSP → CSRF to attacker server with user credentials.
- HTTP `backendUrl` in cloud mode → browser sends credentials over unencrypted HTTP.
- Risk is Low because it requires a prior CI/CD compromise — but the CSP should not amplify the blast radius of such an attack.

---

## Affected surface

- Files: `signalpilot/web/middleware.ts:47-49`
- Endpoints: CSP header on all pages
- Auth modes: Both cloud and local

---

## Proposed fix

Validate the `backendUrl` at build time and refuse to start if it is invalid in cloud mode:

```typescript
// middleware.ts — or better in next.config.ts:
function validateBackendUrl(url: string): string {
  const IS_CLOUD = process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud";
  try {
    const parsed = new URL(url);
    if (IS_CLOUD && parsed.protocol !== "https:") {
      throw new Error(`NEXT_PUBLIC_BACKEND_URL must use HTTPS in cloud mode (got: ${url})`);
    }
    // Only allow expected domains in cloud mode
    const allowedSuffixes = [".signalpilot.ai", "localhost"];
    const isAllowed = allowedSuffixes.some(s => parsed.hostname.endsWith(s));
    if (IS_CLOUD && !isAllowed) {
      throw new Error(`NEXT_PUBLIC_BACKEND_URL hostname not in allowlist: ${parsed.hostname}`);
    }
    return url;
  } catch (e) {
    if (IS_CLOUD) throw e; // Fail build in cloud mode
    return url; // Permissive in local mode
  }
}

const backendUrl = validateBackendUrl(
  process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000"
);
```

Move this validation to `next.config.ts` to fail the build rather than the runtime middleware.

---

## Verification / test plan

**Unit tests:**
1. `test_http_backend_url_rejected_in_cloud` — cloud mode, HTTP backend URL, assert error at build/startup.
2. `test_unknown_domain_rejected_in_cloud` — cloud mode, `https://attacker.com`, assert error.
3. `test_local_mode_permissive` — local mode, any URL, assert accepted.

---

## Rollout / migration notes

- No data migration.
- Cloud deployments must set `NEXT_PUBLIC_BACKEND_URL=https://gateway.signalpilot.ai`.
- Rollback: remove validation.
