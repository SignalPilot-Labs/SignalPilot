# `CLERK_SECRET_KEY` referenced in `middleware.ts` comment but not validated; `auth.py` logs error instead of failing startup

- Slug: clerk-secret-key-required-but-not-validated-at-startup
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/auth.py:25-29`

Back to [issues.md](issues.md)

---

## Problem

In cloud mode, `auth.py` detects a missing `CLERK_PUBLISHABLE_KEY` at module import time and logs an error — but does not fail the process:

```python
# auth.py:25-29
if is_cloud_mode() and not os.environ.get("CLERK_PUBLISHABLE_KEY"):
    logger.error(
        "Cloud mode is enabled (SP_DEPLOYMENT_MODE=cloud) but CLERK_PUBLISHABLE_KEY is not set. "
        "JWT authentication will fail."
    )
    # No sys.exit(), no exception — process continues
```

Consequences:
1. The gateway starts successfully and passes health checks.
2. CI/CD pipelines mark the deployment as healthy.
3. Every authenticated request then fails with 500 or 401 (depending on where the error manifests — `_get_jwks_client()` returns `None`, causing `HTTPException(500)` at line 106).
4. The error is buried in logs; on-call sees a surge of 500s without a clear root cause.

A similar issue exists for `CLERK_SECRET_KEY` on the Next.js side — the Clerk middleware throws at runtime rather than at build time if the key is missing.

Contrast with `SP_ENCRYPTION_KEY` which correctly raises `RuntimeError` at startup (store.py:229-233) — that pattern should be applied to auth config too.

---

## Impact

- Misconfigured cloud deploy appears healthy in CI/CD monitoring.
- All authenticated users get 500 errors until the configuration is corrected.
- Diagnosis is delayed because health checks pass and the error only manifests on auth requests.
- Operational risk: if an automated rollout deploys a misconfigured version, the team may not notice until user reports arrive.

---

## Exploit scenario

This is an operational risk, not a direct exploit. A configuration error silently ships to production:

1. `CLERK_PUBLISHABLE_KEY` is rotated in the secrets store but not updated in the gateway deploy manifest.
2. New gateway pod starts — logs `ERROR: CLERK_PUBLISHABLE_KEY is not set` — health check passes (it checks `/health`, which does not require auth).
3. All users get 500 on login.
4. On-call takes 15+ minutes to identify the root cause from the gateway logs.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/auth.py:25-29`
- Endpoints: All cloud-mode authenticated endpoints
- Auth modes: Cloud mode only

---

## Proposed fix

Raise `SystemExit(1)` at startup if cloud mode and required keys are missing:

```python
# auth.py — updated:
if is_cloud_mode() and not os.environ.get("CLERK_PUBLISHABLE_KEY"):
    raise SystemExit(
        "FATAL: SP_DEPLOYMENT_MODE=cloud but CLERK_PUBLISHABLE_KEY is not set. "
        "Set CLERK_PUBLISHABLE_KEY to proceed."
    )
```

Or, integrate into the `lifespan` validation (see [clerk-publishable-key-derives-issuer-via-base64](clerk-publishable-key-derives-issuer-via-base64-proposal.md)):

```python
# main.py:lifespan:
if is_cloud_mode():
    from .auth import validate_clerk_config
    validate_clerk_config()  # Raises RuntimeError if misconfigured
```

The Kubernetes/ECS deployment will see a non-zero exit code and keep the previous replica running, preventing a silent rollout of a broken configuration.

Similarly, for the Next.js app: add an explicit startup check in `next.config.ts`:

```typescript
// next.config.ts:
if (process.env.NEXT_PUBLIC_DEPLOYMENT_MODE === "cloud") {
  if (!process.env.CLERK_SECRET_KEY) {
    throw new Error("CLERK_SECRET_KEY is required in cloud mode");
  }
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    throw new Error("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is required in cloud mode");
  }
}
```

---

## Verification / test plan

**Unit tests:**
1. `test_missing_publishable_key_cloud_raises` — `is_cloud_mode=True`, `CLERK_PUBLISHABLE_KEY` unset, import `auth.py`, assert `SystemExit`.
2. `test_missing_publishable_key_local_logs_only` — `is_cloud_mode=False`, import `auth.py`, assert no exit, only log.

**Manual checklist:**
- Start gateway with `SP_DEPLOYMENT_MODE=cloud` and `CLERK_PUBLISHABLE_KEY` unset.
- Before fix: process starts, logs error, health check returns 200.
- After fix: process exits with code 1.
- Kubernetes: previous replica continues serving traffic.

---

## Rollout / migration notes

- No data migration.
- Ensure the key is set in all environments before deploying this change.
- Rollback: revert to `logger.error` instead of `SystemExit`.

**Related findings:** [clerk-publishable-key-derives-issuer-via-base64](clerk-publishable-key-derives-issuer-via-base64-proposal.md)
