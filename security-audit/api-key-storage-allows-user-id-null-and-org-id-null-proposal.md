# API keys with `org_id=None`/`"local"` are accepted in cloud mode

- Slug: api-key-storage-allows-user-id-null-and-org-id-null
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:1370-1388`, `signalpilot/gateway/gateway/mcp_auth.py:234-241`

Back to [issues.md](issues.md)

---

## Problem

When `create_api_key` runs, it resolves the org ID with the same `or "local"` fallback used throughout `store.py`:

```python
# store.py:1370
oid = self.org_id or "local"
raw_key = "sp_" + secrets.token_hex(16)
key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
key_id = str(uuid.uuid4())

db_key = GatewayApiKey(
    id=key_id, org_id=oid, user_id=self.user_id, ...
)
```

If `self.org_id` is `None` or empty when `create_api_key` is called (e.g., via a CLI tool, a background migration script, or a request where `resolve_org_id` failed silently), the key is stored with `org_id="local"`.

When this key is later presented to `MCPAuthMiddleware`, the middleware uses `matched.org_id` as the definitive org for the request:

```python
# mcp_auth.py:234
key_org_id = matched.org_id or "local"
```

This means:
1. A key created with `org_id="local"` authenticates every subsequent request as the `"local"` org.
2. In cloud mode, the `"local"` org is a shared namespace potentially containing data from other misconfigured requests.
3. This is the feeding mechanism for the cross-tenant data exposure in finding [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md).

There is also no validation that `user_id` is set — a key with `user_id=None` creates attribution gaps in audit logs.

---

## Impact

- API keys with `org_id="local"` grant access to the shared `"local"` namespace in cloud mode.
- If an admin creates a key while their request context is missing org info (edge case but possible), the key becomes permanently misconfigured.
- These keys do not expire unless explicitly set, so the misconfiguration persists indefinitely.
- Audit logs for requests using these keys show `org_id="local"` instead of a real org, creating attribution gaps.

---

## Exploit scenario

1. Admin uses a management CLI or script that constructs a `Store` without JWT context:
   ```python
   # Hypothetical management script:
   store = Store(session)  # No org_id — defaults to "local"
   record, key = await store.create_api_key(name="cli-key", scopes=["read"])
   ```
2. Key is stored with `org_id="local"`.
3. Admin distributes the key to a service account.
4. Service account presents key to MCP endpoint.
5. `MCPAuthMiddleware` resolves `org_id="local"`.
6. All data operations target the `"local"` org — potentially a shared namespace in cloud mode.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:1370-1388`, `signalpilot/gateway/gateway/mcp_auth.py:234-241`
- Endpoints: `POST /api/keys` (key creation), MCP endpoints (key validation)
- Auth modes: Cloud mode (local mode uses "local" intentionally)

---

## Proposed fix

In cloud mode, refuse to create keys without a valid org_id:

```python
# store.py:create_api_key — add validation:
from .deployment import is_cloud_mode

async def create_api_key(self, name: str, scopes: list[str], expires_at: str | None = None):
    oid = self.org_id or "local"
    if is_cloud_mode() and oid == "local":
        raise ValueError(
            "Cannot create API key without a valid org_id in cloud mode. "
            "Ensure the request is authenticated with a Clerk JWT that contains org_id."
        )
    if is_cloud_mode() and not self.user_id:
        raise ValueError("Cannot create API key without a valid user_id in cloud mode.")
    ...
```

Also validate in `mcp_auth.py` that `matched.org_id` is not `"local"` in cloud mode:

```python
# mcp_auth.py:
from .deployment import is_cloud_mode

key_org_id = matched.org_id or "local"
if is_cloud_mode() and key_org_id == "local":
    logger.error(
        "API key %s has org_id='local' in cloud mode — rejecting. "
        "This key was likely created incorrectly; please rotate it.",
        matched.id,
    )
    await _send_401(send, "Invalid API key configuration. Please contact support.")
    return
```

---

## Verification / test plan

**Unit tests:**
1. `test_create_key_cloud_no_org_id_raises` — mock `is_cloud_mode=True`, `store.org_id=None`, call `create_api_key`, assert `ValueError`.
2. `test_create_key_local_no_org_id_uses_local` — `is_cloud_mode=False`, assert key created with `org_id="local"`.
3. `test_mcp_auth_local_org_key_rejected_in_cloud` — validate key with `org_id="local"` in cloud mode, assert 401.

**Manual checklist:**
- Query DB: `SELECT id, org_id, user_id FROM gateway_api_keys WHERE org_id = 'local'`.
- For any found rows in a cloud deployment, investigate creation context and rotate.

---

## Rollout / migration notes

- **One-time audit:** Scan existing `gateway_api_keys` rows for `org_id = 'local'` or `org_id IS NULL` in production. Rotate or delete these keys before enabling the validation guard.
- After audit, deploy the creation-time validation and the MCP rejection.
- Rollback: remove the `is_cloud_mode()` checks from both functions.

**Related findings:** [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md), [mcp-auth-key-lookup-leaks-cross-tenant-keys](mcp-auth-key-lookup-leaks-cross-tenant-keys-proposal.md)
