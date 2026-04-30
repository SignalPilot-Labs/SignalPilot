# JWKS client has no failure-mode policy and uses default `cache_keys=True` only

- Slug: clerk-jwks-fetched-without-tls-pinning-or-failure-policy
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/auth.py:39-60`

Back to [issues.md](issues.md)

---

## Problem

The JWKS client is initialized as a module-level singleton in `_get_jwks_client()`:

```python
# auth.py:56
_jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
```

There is no explicit failure policy when the JWKS endpoint is unreachable:
1. If Clerk's JWKS endpoint is down (outage, DNS failure, or network partition), `client.get_signing_key_from_jwt(token)` will raise an exception that propagates as an unhandled 500.
2. There is no stale-key fallback: if the cached keys are evicted and Clerk is unreachable, all new JWTs fail verification even if the signing key has not changed.
3. No TLS pinning is configured. PyJWT uses the system CA bundle, which is correct for a public CA-signed endpoint but means a compromised CA could MITM the JWKS response and supply attacker-controlled public keys.
4. JWKS rotation (Clerk rotating its signing keys) is not surfaced in logs or metrics, making silent auth failures hard to debug.

The operational risk is the most immediate: a brief Clerk JWKS outage causes a complete auth outage for the gateway, even for users whose tokens were valid and cached locally in the browser.

---

## Impact

- Clerk JWKS outage → 100% auth failure on the gateway (all cloud-mode requests return 500).
- No user-facing explanation; clients receive a generic server error.
- No TLS pinning means a compromised certificate authority could supply attacker-controlled JWKS, potentially bypassing JWT verification (extremely low probability but not zero for nation-state threats).

---

## Exploit scenario

Not directly exploitable by an external attacker. Operational risk:

1. Clerk's JWKS endpoint experiences a 5-minute partial outage.
2. Gateway pods attempt to refresh keys on the next request.
3. `get_signing_key_from_jwt` raises `PyJWKClientConnectionError`.
4. This propagates up through `resolve_user_id` and is caught by the global exception handler as a 500 (not a clean 401 or 503).
5. All authenticated gateway users see a 500 until Clerk recovers.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/auth.py:39-60`
- Endpoints: All cloud-mode endpoints
- Auth modes: Cloud mode JWT path only

---

## Proposed fix

1. Wrap `get_signing_key_from_jwt` in an explicit except for `PyJWKClientConnectionError` and return a 503 with a clear message:

```python
from jwt.exceptions import PyJWKClientConnectionError

try:
    signing_key = client.get_signing_key_from_jwt(token)
except PyJWKClientConnectionError as exc:
    logger.error("JWKS endpoint unreachable: %s", exc)
    raise HTTPException(
        status_code=503,
        detail="Authentication service temporarily unavailable. Please retry."
    )
```

2. Consider configuring `PyJWKClient` with a longer cache TTL and `lifespan` that allows stale-key usage during outages:

```python
_jwks_client = jwt.PyJWKClient(
    jwks_url,
    cache_keys=True,
    max_cached_keys=10,
    lifespan=86400,  # cache keys for 24h even if Clerk is unreachable
)
```

3. Log JWKS refresh events at INFO level for operational visibility.

4. Add startup validation (see also [clerk-publishable-key-derives-issuer-via-base64](clerk-publishable-key-derives-issuer-via-base64-proposal.md)) that confirms the JWKS URL is reachable before accepting traffic.

---

## Verification / test plan

**Unit tests:**
1. `test_jwks_outage_returns_503` — mock `get_signing_key_from_jwt` to raise `PyJWKClientConnectionError`, assert 503 response with message.
2. `test_jwks_normal_returns_200` — normal path, assert 200.

**Manual checklist:**
- Block outbound HTTPS to the Clerk JWKS URL (firewall rule or DNS override).
- Send authenticated request to gateway.
- Before fix: 500 with traceback in logs. After fix: 503 with user-friendly message.

---

## Rollout / migration notes

- No data migration. Drop-in change to error handling.
- Customer-visible impact: 500s become 503s during Clerk outages — clients that retry on 503 will recover automatically.
- Rollback: remove the `except PyJWKClientConnectionError` block.
