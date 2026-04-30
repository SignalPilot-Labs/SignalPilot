# API key validation has no per-key brute-force limiter; `_auth_rpm=10` only applies to `/api/keys` mgmt endpoint

- Slug: auth-rate-limit-per-ip-only-allows-key-brute-force-from-many-ips
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/middleware.py:231,248`, `signalpilot/gateway/gateway/mcp_auth.py:227`

Back to [issues.md](issues.md)

---

## Problem

`RateLimitMiddleware` defines an `AUTH_PATHS` bucket for key management:

```python
# middleware.py:231
AUTH_PATHS = frozenset({"/api/keys"})
```

The auth rate limit (10 rpm) applies only to `POST /api/keys` — the key creation endpoint. It does NOT apply to:
- The MCP endpoint where API keys are validated (`MCPAuthMiddleware` is in a separate ASGI stack entirely).
- The API key validation path within `APIKeyAuthMiddleware`.
- Any endpoint where an attacker presents an invalid `sp_...` token — the resulting 401 is not tracked in the auth bucket.

The general bucket allows 10,000 rpm per IP. An attacker making 401 responses via invalid API keys hits the general bucket (10,000 rpm per IP = ~167 attempts/second per IP). Distributing across 10 IPs = 1,670 attempts/second.

With 128-bit key space, brute force is computationally infeasible. However:
- The key prefix (7 chars = 32 bits) is leaked via `GET /api/keys` for admin accounts.
- Leaked prefixes narrow the search space for a targeted attack.
- Credential stuffing (using actual leaked keys from other sources) is not rate-limited per attempted key.

---

## Impact

- No per-attempted-key rate limiting on invalid auth responses.
- Credential stuffing with a list of stolen `sp_...` keys is not throttled beyond the general IP rate limit.
- An attacker who compromise an admin account and reads the key list (prefixes) can prioritize their brute-force attempts.
- For finding [api-key-prefix-too-short-and-collidable](api-key-prefix-too-short-and-collidable-proposal.md): with only 32 bits of public prefix, a targeted attack focusing on matching the prefix reduces the effective search space.

---

## Exploit scenario

**Credential stuffing:**
1. Attacker obtains a list of `sp_...` keys from a data breach (e.g., from a previous unrelated breach where a user reused their SignalPilot key).
2. Attacker sends each key to the gateway:

```bash
for key in $(cat stolen-keys.txt); do
  curl https://gateway.signalpilot.ai/mcp \
    -H "X-API-Key: $key" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"tools/list"}'
done
```

3. Rate limiter does not track failed auth attempts per IP (general bucket at 10,000 rpm per IP).
4. Attacker can try ~167 keys/second from one IP.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/middleware.py:231,248`, `signalpilot/gateway/gateway/mcp_auth.py:227`
- Endpoints: All endpoints with API key auth (gateway API and MCP)
- Auth modes: API key auth in cloud mode

---

## Proposed fix

Track auth failures and consume from the auth rate limit bucket:

```python
# middleware.py — APIKeyAuthMiddleware:
async def dispatch(self, request: Request, call_next):
    ...
    if not matched:
        # Consume from auth bucket for any 401/403 response
        ip = self._client_ip(request)
        if not self._check_rate(self._auth_hits[ip], self.auth_rpm):
            return Response(status_code=429, ...)
        return Response(status_code=401, ...)
    ...
```

For MCP, add to `MCPAuthMiddleware`:

```python
# mcp_auth.py:
from ._rate_limit import check_auth_rate  # Shared rate limiter

raw_key = _extract_bearer_key(scope) or _extract_api_key_header(scope)
if not raw_key:
    # Every unauthenticated attempt consumed from auth bucket
    client_ip = _extract_client_ip(scope)
    if not check_auth_rate(client_ip):
        await _send_429(send, "Too many authentication attempts")
        return
    await _send_401(send, "Authentication required")
    return

matched = await store.validate_stored_api_key(raw_key)
if matched is None:
    client_ip = _extract_client_ip(scope)
    check_auth_rate(client_ip)  # Consume regardless of return value
    await _send_401(send, "Invalid API key.")
    return
```

Also consume the auth bucket for any response that is a 401 or 403 in the gateway (to cover all authentication failure paths):

```python
# In global exception handler or response middleware:
if response.status_code in (401, 403):
    ip = _client_ip(request)
    rate_limit_state.consume_auth(ip)
```

---

## Verification / test plan

**Unit tests:**
1. `test_repeated_invalid_keys_triggers_auth_rate_limit` — 11 invalid key attempts from same IP, assert 429 on 11th.
2. `test_valid_key_not_consumed_from_auth_bucket` — valid key, assert auth bucket not consumed.
3. `test_auth_limit_separate_from_general_limit` — auth limit (10/min) does not affect general limit (10000/min) for other endpoints.

---

## Rollout / migration notes

- The auth rate limit per IP is currently 10 rpm (`auth_rpm=10` from `main.py:285`). This may be too low for legitimate scenarios (e.g., automated MCP clients reconnecting rapidly). Consider increasing to 100 rpm for auth failures.
- No data migration.
- Rollback: remove the auth bucket consumption from auth failure paths.

**Related findings:** [api-key-no-scope-for-mcp-and-no-rate-limit-per-key](api-key-no-scope-for-mcp-and-no-rate-limit-per-key-proposal.md), [api-key-prefix-too-short-and-collidable](api-key-prefix-too-short-and-collidable-proposal.md)
