# API key rate-limit is per-IP, not per-key — stolen key behind CDN cannot be throttled

- Slug: api-key-no-scope-for-mcp-and-no-rate-limit-per-key
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/middleware.py:219-323`

Back to [issues.md](issues.md)

---

## Problem

`RateLimitMiddleware` buckets all rate limits by client IP:

```python
# middleware.py:276-282
def _client_ip(self, request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
```

The three rate limit tiers (general, expensive, auth) all key on the same IP. There is no per-key-id bucket and no per-org-id bucket.

Consequences:
1. **Stolen key behind a CDN:** An attacker who obtains a valid API key and routes traffic through a CDN (Cloudflare, Akamai) presents the CDN's egress IP to the gateway. The CDN's IP is a shared IP used by millions of clients. The gateway sees only CDN IPs in the rightmost X-Forwarded-For position and cannot distinguish the attacker's traffic from legitimate CDN traffic.
2. **Distributed key abuse:** An attacker distributing requests across multiple IPs (botnets, proxies) is also not rate-limited per key.
3. **Scope gap for MCP:** The MCP endpoint uses `MCPAuthMiddleware` (separate ASGI middleware) which does not flow through `RateLimitMiddleware` at all — MCP requests are entirely unrated.

The general bucket is 10,000 rpm — effectively no limit for cloud abuse scenarios.

---

## Impact

- A compromised API key cannot be throttled at the key level until it is revoked.
- An attacker with a stolen key can drain a connected data warehouse or exhaust the org's query budget without hitting any per-key rate limit.
- The 5-minute revocation delay (finding [api-keys-cached-by-mcp-auth-in-process-with-no-revocation-bus](api-keys-cached-by-mcp-auth-in-process-with-no-revocation-bus-proposal.md)) compounds this: during the revocation window, there is no throttle on the attacker's key.

---

## Exploit scenario

1. Attacker exfiltrates API key `sp_...` via phishing.
2. Attacker routes requests through Cloudflare Workers (shared IP):

```bash
# From Cloudflare Worker, loop:
for i in $(seq 1 10000); do
  curl https://gateway.signalpilot.ai/mcp \
    -H "X-API-Key: sp_stolen_key" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"execute_query","arguments":{"connection_name":"prod","query":"SELECT * FROM orders"}}}'
done
```

3. Gateway sees Cloudflare's IP; rate limit applies to Cloudflare IP (shared with millions of users).
4. Effectively no rate limiting per the attacker's key.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/middleware.py:219-323`, MCP ASGI stack (`mcp_auth.py`)
- Endpoints: All API endpoints (per-IP only); MCP endpoints (no rate limit at all)
- Auth modes: API key and JWT paths

---

## Proposed fix

Add per-key-id and per-org-id buckets:

```python
# middleware.py — extend RateLimitMiddleware:
self._key_hits: dict[str, list[float]] = defaultdict(list)
self._org_hits: dict[str, list[float]] = defaultdict(list)

async def dispatch(self, request: Request, call_next):
    ...
    key_id = getattr(request.state, "auth", {}).get("key_id")
    org_id = getattr(request.state, "auth", {}).get("org_id")

    if key_id:
        if not self._check_rate(self._key_hits[key_id], self.per_key_rpm):
            return Response(status_code=429, content='{"detail":"Per-key rate limit exceeded"}')
    if org_id and org_id != "local":
        if not self._check_rate(self._org_hits[org_id], self.per_org_rpm):
            return Response(status_code=429, content='{"detail":"Per-org rate limit exceeded"}')
```

For MCP, add rate limiting in `MCPAuthMiddleware` after successful key validation:

```python
# mcp_auth.py — after key validation:
# Simple in-process per-key counter
if not _rate_check_key(matched.id):
    await _send_429(send, "Rate limit exceeded for this API key.")
    return
```

Configurable limits:
- `SP_PER_KEY_RPM=1000` (per API key per minute)
- `SP_PER_ORG_RPM=5000` (per org per minute across all keys)

---

## Verification / test plan

**Unit tests:**
1. `test_per_key_rate_limit_exceeded` — send 1001 requests with same key in 1 minute, assert 429 on 1001st.
2. `test_per_org_rate_limit_exceeded` — two keys same org, combined traffic exceeds org limit, assert 429.
3. `test_per_ip_rate_limit_unchanged` — existing per-IP tests still pass.

**Manual checklist:**
- Send 100 requests/sec with a single key. Confirm 429 after configured limit.
- Rotate key. Confirm new key starts at zero count.

---

## Rollout / migration notes

- New env vars: `SP_PER_KEY_RPM`, `SP_PER_ORG_RPM`. Default to permissive values initially (e.g., 10,000) and tighten over time.
- Existing per-IP limits unchanged.
- In-memory only; resets on gateway restart. For persistent rate limiting, use Redis.
- Rollback: remove per-key/per-org bucket checks.
