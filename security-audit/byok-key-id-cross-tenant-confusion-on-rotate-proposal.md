# BYOK rotate accepts attacker-controlled `new_key_id` — only checks `org_id == org_id` post-hoc

- Slug: byok-key-id-cross-tenant-confusion-on-rotate
- Severity: Low
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/gateway/gateway/api/byok.py:353-409`

Back to [issues.md](issues.md)

---

## Problem

The BYOK key rotation endpoint looks up both the source (`key_id`) and target (`body.new_key_id`) BYOK keys by ID with no `org_id` filter in the database query:

```python
# api/byok.py:372-384
old_key_result = await store.session.execute(
    select(GatewayBYOKKey).where(GatewayBYOKKey.id == key_id)
)
old_key = old_key_result.scalar_one_or_none()
if old_key is None or old_key.org_id != org_id or old_key.status not in ("active", "rotating"):
    raise HTTPException(status_code=404, detail="Key not found")

new_key_result = await store.session.execute(
    select(GatewayBYOKKey).where(GatewayBYOKKey.id == body.new_key_id)
)
new_key = new_key_result.scalar_one_or_none()
if new_key is None or new_key.org_id != org_id or new_key.status != "active":
    raise HTTPException(status_code=404, detail="Target key not found")
```

The post-hoc `org_id != org_id` check is correct and currently prevents cross-tenant access. However:

1. The pattern is fragile: if a future developer adds a `try/except` around the check, or if the row is returned for logging before the check completes, cross-tenant key material could be exposed.
2. The lookup retrieves the full `GatewayBYOKKey` row (including `key_alias`, `status`, and potentially other metadata) before the org check. Any exception between the query and the check could log the row's contents.
3. Defense-in-depth principle: SQL-level filtering is more reliable than Python-level post-hoc checking.

---

## Impact

- Current risk: Low — the post-hoc check is in place and works.
- Future risk: Medium — a developer refactoring the error-handling path could inadvertently expose another org's key alias or metadata before the org check.
- Attack: An attacker with valid org membership who guesses a BYOK key UUID from another org would receive a 404 — correct behavior. The UUID is a random v4, so guessing is not feasible.

---

## Exploit scenario

Current code is resistant. Hypothetical future regression:

```python
# Imagine a refactor that logs the row before checking:
old_key = old_key_result.scalar_one_or_none()
logger.info("Rotating key: %s (alias: %s)", old_key.id, old_key.key_alias)  # <-- logs other tenant's alias
if old_key is None or old_key.org_id != org_id:
    raise HTTPException(status_code=404)
```

The key alias (e.g., an AWS KMS key ARN) from another tenant would be logged before the org check rejects the request.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/api/byok.py:353-409`
- Endpoints: `POST /api/byok/keys/{key_id}/rotate`
- Auth modes: Cloud and local; requires `admin` scope

---

## Proposed fix

Add `org_id` to the WHERE clause in both queries:

```python
# api/byok.py — updated queries:
old_key_result = await store.session.execute(
    select(GatewayBYOKKey).where(
        GatewayBYOKKey.id == key_id,
        GatewayBYOKKey.org_id == org_id,  # Filter in SQL, not post-hoc
    )
)
old_key = old_key_result.scalar_one_or_none()
if old_key is None or old_key.status not in ("active", "rotating"):
    raise HTTPException(status_code=404, detail="Key not found")

new_key_result = await store.session.execute(
    select(GatewayBYOKKey).where(
        GatewayBYOKKey.id == body.new_key_id,
        GatewayBYOKKey.org_id == org_id,  # Filter in SQL
    )
)
new_key = new_key_result.scalar_one_or_none()
if new_key is None or new_key.status != "active":
    raise HTTPException(status_code=404, detail="Target key not found")
```

Apply the same pattern to all other BYOK endpoints that look up keys by ID.

---

## Verification / test plan

**Unit tests:**
1. `test_rotate_byok_cross_tenant_key_id_returns_404` — pass a `key_id` belonging to a different org, assert 404.
2. `test_rotate_byok_cross_tenant_new_key_id_returns_404` — valid `key_id` but `new_key_id` from another org, assert 404.
3. `test_rotate_byok_same_org_succeeds` — valid rotation within same org, assert success.

---

## Rollout / migration notes

- No data migration.
- This is a tightening of the SQL query; no behavior change for correct (same-org) callers.
- Rollback: remove the `GatewayBYOKKey.org_id == org_id` conditions.

**Related findings:** [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md)
