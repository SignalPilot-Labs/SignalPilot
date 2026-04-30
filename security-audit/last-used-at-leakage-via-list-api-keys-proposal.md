# `GET /api/keys` returns `last_used_at` per key — leaks usage telemetry to admin users

- Slug: last-used-at-leakage-via-list-api-keys
- Severity: Info
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/api/keys.py:14-20`, `signalpilot/gateway/gateway/store.py:1353-1366,1404-1432`

Back to [issues.md](issues.md)

---

## Problem

```python
# api/keys.py:14-20
@router.get("/keys", dependencies=[RequireScope("admin")])
async def list_keys(store: StoreD) -> list[ApiKeyResponse]:
    records = await store.list_api_keys()
    return [
        ApiKeyResponse(**r.model_dump(exclude={"key_hash", "user_id"}))
        for r in records
    ]
```

`ApiKeyResponse` includes `last_used_at`, populated on every successful `validate_stored_api_key` call (`store.py:1426`). The `last_used_at` write happens unconditionally on every authenticated MCP / API request, including from third-party agents.

In a multi-user organization where multiple admins share key visibility, `last_used_at` reveals:

- Whether a particular key has been used recently (ie. is "live" or "stale").
- Approximate request frequency, when polled.

For dormant keys created by a former employee, `last_used_at` doubles as a side-channel: if `last_used_at` advances, someone else still has the key (e.g. compromised CI). This is a *useful* signal for defenders, but it's also visible to anyone with `admin` scope on the org — which by design includes any IdP-mapped admin role.

This is not a vulnerability in the strict sense; it's a design note that some teams want to surface `last_used_at` only to the original key creator, not to all org admins.

Also: `last_used_at` is updated **on every request** with a SQL `UPDATE` (`store.py:1426`), introducing write amplification. For high-rps keys, the SQL `UPDATE` runs on every request and serializes all reads through a row-level lock.

---

## Impact

- Privacy: timing of key usage visible to all org admins.
- Performance: per-request `UPDATE` on the `GatewayApiKey` row creates write contention at high rps.
- Forensics: legitimate use case for the field exists; balance is needed.

---

## Exploit scenario

Two admins in the same Clerk org. Admin A creates a key for personal use (e.g. local dev tooling). Admin B watches `GET /api/keys` and sees Admin A's `last_used_at` advance during off-hours, inferring after-hours work.

Lower-impact than a security bug; included for completeness.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/api/keys.py:14-20`, `signalpilot/gateway/gateway/store.py:1353-1366,1404-1432`.
- Endpoints: `GET /api/keys`.
- Auth modes: cloud + local; requires `admin` scope.

---

## Proposed fix

- Throttle `last_used_at` writes to once per minute per key (cache the timestamp in the existing `_KeyCache` and only flush periodically).
- Optionally: only return `last_used_at` to the key's creator (`user_id` matches the JWT `sub`); for other admins, return a coarser bucket (`"this hour" / "this week"`).
- Add a separate `usage_24h` counter computed from audit logs for ops dashboards.

---

## Verification / test plan

- Unit: `tests/test_keys_api.py::test_last_used_throttled` — assert >1 successful validation in <60s does not produce >1 UPDATE.
- Unit: `tests/test_keys_api.py::test_non_creator_admin_sees_coarse_bucket`.

---

## Rollout / migration notes

- API contract change for `last_used_at` (string ISO → bucket); document in changelog.
- Rollback: revert response shape; non-destructive.
