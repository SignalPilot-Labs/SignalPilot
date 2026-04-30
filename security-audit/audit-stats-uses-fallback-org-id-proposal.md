# `/api/audit/stats` queries `org_id = store.org_id or "local"` — fallback risk

- Slug: audit-stats-uses-fallback-org-id
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/api/audit.py:41`

Back to [issues.md](issues.md)

---

## Problem

`get_audit_stats` directly computes `oid = store.org_id or "local"` in the endpoint body rather than relying on a centralized org resolution:

```python
# api/audit.py:41-49
async def get_audit_stats(store: StoreD):
    from sqlalchemy import case, Integer
    oid = store.org_id or "local"
    q = (
        select(...)
        .where(GatewayAuditLog.org_id == oid)
        .group_by(GatewayAuditLog.event_type)
    )
```

This is the same pattern as the 18 occurrences in `store.py` (finding [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md)), called out separately because:

1. It bypasses the centralized `_require_org_id` guard that should be added to `Store`.
2. If `store.org_id` is `None` or empty in cloud mode — due to a middleware fault or an edge case in `resolve_org_id` — this endpoint silently queries the `"local"` org's audit data rather than the requesting user's org.
3. This is an audit endpoint: leaking audit data cross-tenant is particularly sensitive because it reveals which queries were run, against which connections, and whether any were blocked by governance rules.

This is a subset of finding #11 but flagged separately to ensure the audit.py file gets explicit attention during remediation, since it is not inside `store.py` and could be missed in a bulk refactor.

---

## Impact

- If `store.org_id` is unset in cloud mode: audit stats for the `"local"` org are returned instead of the requesting user's org stats.
- The `"local"` org's audit data could include data from other tenants that triggered the `"local"` fallback (see finding #11).
- Attacker can observe query patterns and governance block statistics for other tenants' workloads.

---

## Exploit scenario

1. Attacker presents a valid JWT but the `resolve_org_id` dependency has a bug that leaves `store.org_id=None` (e.g., during a code refactor that breaks the dependency chain).
2. Attacker calls `GET /api/audit/stats`.
3. Response contains aggregate stats for the `"local"` org, not the attacker's org.
4. In a misconfigured deployment, the `"local"` org may contain rows from multiple real tenants.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/api/audit.py:41`
- Endpoints: `GET /api/audit/stats`
- Auth modes: Cloud mode JWT and API key paths

---

## Proposed fix

After implementing `_require_org_id` in `Store` (finding #11), update the endpoint to use it:

```python
# api/audit.py — updated:
async def get_audit_stats(store: StoreD):
    from sqlalchemy import case, Integer
    oid = store._require_org_id()  # raises in cloud mode if org_id unset
    q = (
        select(...)
        .where(GatewayAuditLog.org_id == oid)
        .group_by(GatewayAuditLog.event_type)
    )
```

Or better, move the query into `store.py` as a method:

```python
# store.py:
async def get_audit_stats(self) -> dict[str, Any]:
    oid = self._require_org_id()
    ...
```

---

## Verification / test plan

**Unit tests:**
1. `test_audit_stats_requires_org_id_in_cloud` — mock `store.org_id=None`, `is_cloud_mode=True`, assert 500/ValueError before DB query.
2. `test_audit_stats_correct_org_filter` — assert SQL WHERE clause uses the requesting user's org_id, not `"local"`.

---

## Rollout / migration notes

- This is a one-line change after the `_require_org_id` refactor from finding #11 is in place.
- No DB migration required.
- Recommended to fix simultaneously with finding #11 in the same PR.

**Related findings:** [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md)
