# `Store` defaults `org_id="local"` when org_id is unset, even in cloud mode

- Slug: org-id-fallback-to-local-in-cloud
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py` — multiple locations (lines 636, 650, 693, 824, 939, 996, 1058, 1066, 1078, 1176, 1193, 1213, 1246, 1343, 1357, 1370, 1391)

Back to [issues.md](issues.md)

---

## Problem

Throughout `store.py`, database operations fall back to the literal string `"local"` when `org_id` is not set:

```python
# Repeated in ~18 locations, e.g.:
# store.py:636, 650, 693, 824, 939, 996, 1058, 1066, 1078, 1176, 1193, 1213, 1246, 1343, 1357, 1370, 1391
oid = self.org_id or "local"
```

This fallback was designed for local single-user deployments. In cloud mode, `org_id` should always be set from the Clerk JWT. However, there are code paths where a `Store` instance can be constructed without a real `org_id`:

1. Background tasks or scheduled jobs that construct `Store(session)` without an org context.
2. Exception paths where `resolve_org_id` fails to populate `request.state._jwt_claims`.
3. The `allow_unscoped=True` path used in MCP auth (line 194 of `mcp_auth.py`), which explicitly constructs a store without an org to list all keys — but if this store is accidentally used for data operations, it silently operates as the `"local"` org.

The `"local"` org in cloud mode is a shared namespace. Any data written to or read from `org_id="local"` is accessible to all other requests that also end up with `org_id="local"` — including the critical bypass in [mcp-auth-passthrough-when-no-keys-exist](mcp-auth-passthrough-when-no-keys-exist-proposal.md).

---

## Impact

- **Silent data exposure:** A background task or edge case that constructs a `Store` without `org_id` in cloud mode reads/writes to the shared `"local"` namespace, potentially exposing data across tenants.
- **Audit confusion:** Audit log entries written with `org_id="local"` do not correlate to any real Clerk org, making incident investigation harder.
- **Cross-tenant data leakage:** If the MCP unauthenticated bypass (finding #7) is not fixed, requests operating as `org_id="local"` can read data written by any other request that accidentally used the `"local"` fallback.

---

## Exploit scenario

Not directly exploitable as a standalone vulnerability. Amplifies the impact of other findings. Example compound scenario:

1. A background job (e.g., scheduled cache refresh) constructs `Store(session)` with no org context.
2. It calls `store.read_connections()` — gets `oid = self.org_id or "local"` = `"local"`.
3. Happens to read connection credentials belonging to the `"local"` org (which is the default for misconfigured keys from finding #18).
4. These credentials are logged or cached without org attribution.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py` at the 18+ locations listed above
- Endpoints: All endpoints that use `StoreD` (via the store dependency)
- Auth modes: Cloud mode (local mode uses `"local"` intentionally)

---

## Proposed fix

Add a cloud-mode guard in the `Store` class that raises instead of falling back:

```python
# store.py — at the class level or in a helper method:
from .deployment import is_cloud_mode

class Store:
    def _require_org_id(self) -> str:
        """Return org_id, raising ValueError in cloud mode if unset."""
        if self.org_id:
            return self.org_id
        if is_cloud_mode() and not self.allow_unscoped:
            raise ValueError(
                "org_id is required in cloud mode but was not set. "
                "Ensure resolve_org_id ran before constructing Store."
            )
        return "local"
```

Then replace all `oid = self.org_id or "local"` with `oid = self._require_org_id()`.

The `allow_unscoped=True` stores (used for key validation) should not call data-operation methods; add assertions to prevent it:

```python
def list_api_keys(self) -> list[ApiKeyRecord]:
    # allow_unscoped stores can call this — it's the intended usage
    ...

def read_connections(self) -> list[Connection]:
    # must not be called on allow_unscoped stores in cloud mode
    if self.allow_unscoped and is_cloud_mode():
        raise ValueError("read_connections requires org-scoped Store")
    oid = self._require_org_id()
    ...
```

---

## Verification / test plan

**Unit tests:**
1. `test_store_cloud_no_org_id_raises` — create `Store(session, allow_unscoped=False)` with no org_id in cloud mode, call `read_connections()`, assert `ValueError`.
2. `test_store_local_no_org_id_uses_local` — same but `is_cloud_mode=False`, assert returns `"local"`.
3. `test_store_allow_unscoped_data_ops_raises` — call `read_connections` on unscoped store in cloud mode, assert `ValueError`.

**Manual checklist:**
- Search for any background tasks or management commands that construct `Store` without an `org_id`.
- Add `is_cloud_mode()` check at each construction site.

---

## Rollout / migration notes

- This is a broad change across `store.py`. Recommend a dedicated PR with full test coverage.
- If any background task legitimately needs cross-tenant access, it must be explicitly marked with `allow_unscoped=True` and restricted to only the operations it needs.
- No DB migration; this is a runtime behavior change.
- Rollback: revert `_require_org_id` to `self.org_id or "local"`.

**Related findings:** [mcp-auth-passthrough-when-no-keys-exist](mcp-auth-passthrough-when-no-keys-exist-proposal.md), [audit-stats-uses-fallback-org-id](audit-stats-uses-fallback-org-id-proposal.md)
