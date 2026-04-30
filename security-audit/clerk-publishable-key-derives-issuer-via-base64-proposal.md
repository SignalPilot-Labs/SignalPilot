# Issuer derivation from publishable key is fragile and silently mis-handles malformed keys

- Slug: clerk-publishable-key-derives-issuer-via-base64
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/auth.py:44-60`

Back to [issues.md](issues.md)

---

## Problem

`_get_jwks_client()` derives the Clerk JWKS URL and expected issuer by base64-decoding the publishable key:

```python
# auth.py:49-58
for prefix in ("pk_test_", "pk_live_"):
    if pk.startswith(prefix):
        encoded = pk[len(prefix):]
        padded = encoded + "=" * (-len(encoded) % 4)
        domain = base64.b64decode(padded).decode("utf-8").rstrip("$")
        jwks_url = f"https://{domain}/.well-known/jwks.json"
        _expected_issuer = f"https://{domain}"
        _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
        return _jwks_client

raise ValueError(f"Cannot derive JWKS URL from publishable key: {pk[:12]}...")
```

Problems:
1. **`ValueError` is raised at first-request time, not at startup.** If `CLERK_PUBLISHABLE_KEY` is set but malformed (e.g., copy-paste error), the first authenticated request raises an unhandled exception. This surfaces as a 500 in logs and is hard to distinguish from application bugs. A misconfigured deploy ships and appears healthy until the first user tries to log in.
2. **No explicit `CLERK_ISSUER` override env var.** If Clerk changes its domain format or introduces a new key prefix, the derivation breaks silently.
3. **`base64.b64decode` can raise `binascii.Error` for malformed padding.** This is caught by the outer `except` in `resolve_user_id` as a generic 500 rather than a startup configuration error.
4. **The `$` stripping in `.rstrip("$")` is undocumented** — it is specific to Clerk's encoding convention and could silently produce wrong domains if Clerk changes the format.

---

## Impact

- Misconfigured cloud deploy accepts traffic but returns 500 for all authenticated requests.
- Healthcheck endpoints (which are unauthenticated) pass, so the deploy appears healthy in CI/CD.
- Discovery of the misconfiguration is delayed until user reports start coming in.

---

## Exploit scenario

This is an operational risk rather than an active exploit. A deploy where `CLERK_PUBLISHABLE_KEY` has a trailing space or incorrect prefix ships through CI/CD undetected. Every authenticated user gets a 500. The on-call engineer must diagnose from logs.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/auth.py:44-60`
- Endpoints: All cloud-mode endpoints requiring JWT auth
- Auth modes: Cloud mode only

---

## Proposed fix

Validate at startup in the `lifespan` function, fail immediately:

```python
# auth.py — add a validate-at-startup function:
def validate_clerk_config() -> None:
    """Raise RuntimeError at startup if Clerk config is invalid in cloud mode."""
    from .deployment import is_cloud_mode
    if not is_cloud_mode():
        return
    pk = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
    if not pk:
        raise RuntimeError("CLERK_PUBLISHABLE_KEY is required in cloud mode")
    client = _get_jwks_client()  # raises ValueError here at startup
    if client is None:
        raise RuntimeError("Could not initialize JWKS client — check CLERK_PUBLISHABLE_KEY format")

# main.py lifespan — call before accepting traffic:
validate_clerk_config()
```

Also expose an override:
```python
# auth.py:_get_jwks_client():
explicit_issuer = os.environ.get("CLERK_ISSUER")
if explicit_issuer:
    _expected_issuer = explicit_issuer
    jwks_url = explicit_issuer.rstrip("/") + "/.well-known/jwks.json"
    _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client
```

---

## Verification / test plan

**Unit tests:**
1. `test_invalid_pk_raises_at_startup` — set malformed `CLERK_PUBLISHABLE_KEY`, call `validate_clerk_config()`, assert `RuntimeError`.
2. `test_clerk_issuer_override` — set `CLERK_ISSUER=https://example.com`, assert JWKS URL derived correctly without parsing `pk`.

**Manual checklist:**
- Set `CLERK_PUBLISHABLE_KEY=pk_live_INVALIDBASE64` in environment.
- Start gateway. Before fix: starts successfully, first request returns 500. After fix: startup fails with RuntimeError logged.

---

## Rollout / migration notes

- No data migration required.
- The startup check adds ~100ms to gateway startup (JWKS HTTP request). Acceptable.
- Rollback: remove the `validate_clerk_config()` call from lifespan.
