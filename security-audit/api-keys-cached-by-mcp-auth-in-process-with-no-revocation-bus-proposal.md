# MCP auth caches validated keys for 5 minutes per process; revocations not propagated

- Slug: api-keys-cached-by-mcp-auth-in-process-with-no-revocation-bus
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/mcp_auth.py:27,46-90`

Back to [issues.md](issues.md)

---

## Problem

`MCPAuthMiddleware` uses an in-process FIFO+TTL cache for validated API keys:

```python
# mcp_auth.py:27
_CACHE_TTL_SECONDS: int = 300  # 5 minutes

# mcp_auth.py:62-72 — _KeyCache.get:
if time.monotonic() - inserted_at > _CACHE_TTL_SECONDS:
    del self._store[key_hash]
    return None
return result
```

When an admin deletes an API key via `DELETE /api/keys/{id}`:
1. The key is removed from the `gateway_api_keys` DB table immediately.
2. However, if the same key was recently validated, its result is cached in `_cache` (the module-level `_KeyCache` instance) for up to 300 seconds.
3. In a multi-replica gateway deployment, each process has its own cache instance. There is no invalidation message bus (no Redis pub/sub, no shared cache, no DB polling on each request).
4. A deleted key continues to authenticate MCP requests for up to 5 minutes per process.

The MCP auth flow uses the gateway's own DB (via `store.validate_stored_api_key`) rather than an external backend validation call. But the `_KeyCache` wraps the entire result of key validation, including the `matched` record — so even with the DB deletion, the cache returns the stale `ApiKeyRecord`.

---

## Impact

- **Revocation lag:** A compromised API key that an admin deletes continues to work for up to 300 seconds across all gateway replicas.
- **In a 3-replica deployment:** Key works on replica A for up to 5 min, replica B for up to 5 min, replica C for up to 5 min — they are independent.
- **Incident response impacted:** During a security incident, the standard first response is to rotate/delete the compromised key. The 5-minute window means an active attacker has 5 more minutes of access after revocation.

---

## Exploit scenario

1. Attacker exfiltrates API key `sp_abc123...` via phishing, logs, or XSS.
2. Admin discovers the compromise and deletes the key: `DELETE /api/keys/{id}`.
3. Attacker continues to use the key for up to 5 minutes:

```bash
# Key deleted at T=0 but still works at T=4:59
curl https://gateway.signalpilot.ai/mcp \
  -H "X-API-Key: sp_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"execute_query","arguments":{...}}}'
# Returns 200 until cache expires
```

4. At T=5:01, all replicas' caches expire and the key is rejected.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/mcp_auth.py:27,46-90`
- Endpoints: All MCP endpoints (gated by `MCPAuthMiddleware`)
- Auth modes: API key auth in cloud and local modes

---

## Proposed fix

**Option A — Reduce cache TTL (fastest fix):**
```python
# mcp_auth.py:27
_CACHE_TTL_SECONDS: int = 30  # 30 seconds instead of 300
```
This limits the revocation window to 30s with no architecture changes.

**Option B — DB liveness check on cache hit (recommended for cloud):**
```python
# mcp_auth.py — in validate_api_key:
async def validate_api_key(key: str, backend_url: str) -> dict[str, Any] | None:
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    cached = _cache.get(key_hash)
    if cached is not None:
        # Fast path: check if key still exists in DB without full validation
        if not await _check_key_still_valid(key_hash):
            _cache.invalidate(key_hash)  # Add invalidate method to _KeyCache
            return None
        return cached
    ...

async def _check_key_still_valid(key_hash: str) -> bool:
    """Lightweight DB existence check — does not re-validate hash, just confirms row exists."""
    from .db.engine import get_session_factory
    from .db.models import GatewayApiKey
    async with get_session_factory()() as session:
        result = await session.execute(
            select(GatewayApiKey.id).where(GatewayApiKey.key_hash == key_hash)
        )
        return result.scalar_one_or_none() is not None
```

This adds one lightweight SELECT per cached request but ensures revocations take effect immediately.

**Option C — Redis invalidation bus (most scalable):**
On key deletion, publish `DELETE:key_hash` to a Redis channel. Each gateway process subscribes and evicts from local cache. Requires adding Redis as an infrastructure dependency.

**Recommendation:** Implement Option A immediately (TTL to 30s), then Option B for zero-lag revocation.

---

## Verification / test plan

**Unit tests:**
1. `test_cache_ttl_respects_config` — assert cache returns None after `_CACHE_TTL_SECONDS`.
2. `test_revoked_key_rejected_immediately` (Option B) — delete key from DB after caching, assert next request returns 401 without waiting for TTL.

**Manual checklist:**
- Create API key, use it successfully (confirm 200).
- Delete key via admin UI.
- Immediately retry: before fix → 200 (cached). After Option B fix → 401.

---

## Rollout / migration notes

- Option A: one-line change, zero risk.
- Option B: requires DB access in the MCP auth hot path; test performance impact (expected: <5ms per request on a local DB).
- Option C: requires Redis infra; multi-week project.
- No data migration for any option.
- Rollback: revert TTL change or remove DB liveness check.
