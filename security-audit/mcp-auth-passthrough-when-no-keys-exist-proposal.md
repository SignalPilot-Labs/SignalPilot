# MCP accepts ALL unauthenticated requests when zero API keys exist

- Slug: mcp-auth-passthrough-when-no-keys-exist
- Severity: Critical
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/mcp_auth.py:196-218`, all MCP tool endpoints

Back to [issues.md](issues.md)

---

## Problem

`MCPAuthMiddleware.__call__` begins by loading the entire global API key list with `store.list_api_keys()` (called with `allow_unscoped=True`, meaning it queries across all organizations). If the result is an empty list, the middleware sets `user_id="local"` and `org_id="local"` and calls the wrapped MCP application without any authentication.

```python
# mcp_auth.py:196-218
keys = await store.list_api_keys()
has_user_keys = len(keys) > 0

if not has_user_keys:
    ...
    mcp_user_id_var.set("local")
    mcp_org_id_var.set("local")
    ...
    scope["state"]["auth"] = {"user_id": "local", "org_id": "local"}
    await self._app(scope, receive, send)
    return
```

There is no check for `is_cloud_mode()` before this branch executes. The branch was designed for the local-development scenario where an operator has not yet created any API keys, but it applies equally to the hosted multi-tenant deployment.

A "zero keys" state occurs in at least three realistic cloud scenarios:
1. A fresh deployment where no admin has yet generated keys.
2. An incident where an admin deletes all keys (intentionally or by mistake).
3. A database migration or rollback that temporarily empties the `gateway_api_keys` table.

During any of these windows, every request to `gateway.signalpilot.ai/mcp` — from the public internet — is served as if it were a local trusted user. The MCP tool surface includes `execute_query` (runs SQL against all stored connections), `list_connections`, `get_schema`, and `execute_code` (if sandbox not disabled). This means an unauthenticated attacker can read all stored encrypted connection credentials, run arbitrary SQL against every connected warehouse, and enumerate audit logs for all tenants.

---

## Impact

- **Unauthenticated access to all MCP tools** during the zero-key window.
- **Cross-tenant data exfiltration**: all connections and query results are accessible as `org_id="local"` bypasses tenant isolation.
- **Multi-tenant blast radius**: because `org_id="local"` is the shared fallback for all unscoped operations (see finding [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md)), the attacker operates as the "local" superuser spanning all data.
- In the worst case, an attacker can run `list_connections`, extract connection IDs, then `execute_query` against each — reading data from every customer's connected warehouse.

---

## Exploit scenario

```bash
# Fresh cloud deploy — no API keys exist yet.
# Attacker discovers the MCP endpoint (advertised in docs / Claude plugin manifest).

curl -X POST https://gateway.signalpilot.ai/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Returns full tool list — no 401.

curl -X POST https://gateway.signalpilot.ai/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_connections","arguments":{}}}'

# Returns all stored connections across all orgs.

curl -X POST https://gateway.signalpilot.ai/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"execute_query","arguments":{"connection_name":"acme-prod","query":"SELECT * FROM customers LIMIT 100"}}}'

# Returns customer data. No authentication required.
```

Attacker steps:
1. No credentials needed; no brute force; no social engineering.
2. Wait for or trigger a zero-key window (e.g., DoS the gateway causing key table migration, or exploit a separate admin-key-delete vulnerability).
3. Enumerate all connections and drain data.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/mcp_auth.py` lines 196-218
- Endpoints: All MCP streamable-http endpoints (mounted at `/` in `main.py:331`)
- Auth modes: Cloud mode with zero API keys in DB; local mode (by design, acceptable)

---

## Proposed fix

In cloud mode, require authentication unconditionally. The "no keys" branch must be restricted to `is_cloud_mode() == False`.

```python
# mcp_auth.py — in MCPAuthMiddleware.__call__, after loading keys:

from .deployment import is_cloud_mode

keys = await store.list_api_keys()
has_user_keys = len(keys) > 0

if not has_user_keys:
    if is_cloud_mode():
        # Cloud: never fall through without auth, even with zero keys.
        # A freshly deployed instance must still require authentication.
        await _send_401(
            send,
            "No API keys configured. Create an API key in the SignalPilot dashboard."
        )
        return
    # Local mode only: pass through for zero-key developer setups.
    ...
```

Additionally, add a startup assertion:

```python
# main.py lifespan — after init_db():
if is_cloud_mode():
    from .mcp_auth import _assert_cloud_auth_configured
    await _assert_cloud_auth_configured()
```

Where `_assert_cloud_auth_configured` logs a Critical-level warning (not a hard startup failure, since keys can be created post-deploy, but the warning should page on-call).

New invariant: in cloud mode, `MCPAuthMiddleware` MUST return 401 if no valid key is presented, regardless of DB state.

Add a unit test:

```python
# tests — MCPAuthMiddleware with is_cloud_mode=True and empty key list
async def test_mcp_auth_cloud_no_keys_returns_401(monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    # mock store.list_api_keys returns []
    response = await call_mcp_without_auth()
    assert response.status_code == 401
```

Backward-compat: No key rotation or migration required. Local deployments are unaffected because the branch is guarded by `is_cloud_mode()`.

---

## Verification / test plan

**Unit tests to add:**
1. `test_mcp_auth_cloud_zero_keys_returns_401` — monkeypatch `is_cloud_mode=True`, `list_api_keys=[]`, assert 401.
2. `test_mcp_auth_local_zero_keys_passes_through` — monkeypatch `is_cloud_mode=False`, `list_api_keys=[]`, assert call succeeds.
3. `test_mcp_auth_cloud_valid_key_passes` — verify valid key still works post-fix.

**Manual repro checklist:**
- Deploy gateway with `SP_DEPLOYMENT_MODE=cloud` and an empty `gateway_api_keys` table.
- Send `POST /mcp` with no `Authorization` header.
- Before fix: returns 200 with tool list. After fix: returns 401.

**What "fixed" looks like:**
```bash
curl -X POST https://gateway.signalpilot.ai/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# Returns: HTTP 401 {"error": "No API keys configured. ..."}
```

---

## Rollout / migration notes

- **Order of operations:** Deploy the patched `mcp_auth.py` before generating the first production API key. The fix ensures the endpoint is locked before keys exist, not after.
- **Customer-visible impact:** Any MCP client (Claude Code plugin) connecting to a freshly deployed gateway will receive 401 until the admin creates an API key. This is the correct behavior. Add clear error messaging in the 401 response body pointing to the dashboard.
- **Rollback plan:** Reverting is safe — the only change is refusing unauthenticated requests in cloud mode when no keys exist, which is never a legitimate use case in production.

**Related findings:** [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md), [api-key-storage-allows-user-id-null-and-org-id-null](api-key-storage-allows-user-id-null-and-org-id-null-proposal.md)
