# MCP API key validated against ALL orgs (validate_stored_api_key has no tenant scope)

- Slug: mcp-auth-key-lookup-leaks-cross-tenant-keys
- Severity: High
- Cloud impact: Yes
- Confidence: Medium
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:1404-1432`, `signalpilot/gateway/gateway/mcp_auth.py:227-241`

Back to [issues.md](issues.md)

---

## Problem

`validate_stored_api_key` performs a cross-tenant lookup with no `org_id` filter:

```python
# store.py:1404-1432 (line offsets from file read)
async def validate_stored_api_key(self, raw_key: str) -> ApiKeyRecord | None:
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    # Search all keys (not org-scoped — validation doesn't know org yet)
    result = await self.session.execute(
        select(GatewayApiKey).where(GatewayApiKey.key_hash == key_hash)
    )
    row = result.scalar_one_or_none()
```

The comment acknowledges this is intentional: at validation time the system does not yet know which org the key belongs to (the org is derived from the key itself). This is architecturally correct — the key's `org_id` is the source of truth for subsequent operations.

The risk arises from the trust relationship: after validation, `matched.org_id` (line 234 of `mcp_auth.py`) is trusted as the authoritative org for the entire request:

```python
# mcp_auth.py:234-240
key_org_id = matched.org_id or "local"
key_user_id = matched.user_id or "local"
scope["state"]["auth"] = {
    "key_id": matched.id,
    "key_name": matched.name,
    "user_id": key_user_id,
    "org_id": key_org_id,
}
```

This creates a trust boundary: if `org_id` was set incorrectly at key creation time (e.g., a bug in `create_api_key` that used `self.org_id or "local"` when `self.org_id` was None in cloud mode), the key is permanently bound to the wrong org. The `matched.org_id` value is then used for all subsequent data access without any secondary verification against the Clerk org of the presenting user.

Additionally, there is no defense-in-depth encoding of the `org_id` in the key prefix itself (e.g., `sp_o_{shortorgid}_...`), meaning a key's org cannot be verified from the key material alone without a DB round-trip.

---

## Impact

- If any API key has `org_id` set incorrectly (e.g., `"local"` instead of a real org ID), the holder of that key gets access to the shared `"local"` org's data, which overlaps with all other misconfigured keys.
- A future code refactoring that returns the `GatewayApiKey` row before checking `org_id` could allow cross-tenant access.
- Current risk: Low, because the hash comparison enforces that only the holder of the exact key can match. The org trust boundary is the medium-risk part.

Confidence is Medium because exploitation requires either a key with a wrong `org_id` in the DB (which depends on a separate bug, such as [api-key-storage-allows-user-id-null-and-org-id-null](api-key-storage-allows-user-id-null-and-org-id-null-proposal.md)) or a future refactor that breaks the check ordering.

---

## Exploit scenario

**Scenario A — wrong org_id at creation time (requires bug #18):**
1. Admin creates a key while the gateway store has `org_id=None` (e.g., via a background task or CLI that bypasses request context).
2. Key is stored with `org_id="local"`.
3. Key holder presents it to the MCP endpoint.
4. `validate_stored_api_key` matches the hash. Returns row with `org_id="local"`.
5. Request operates as the `"local"` org, which in cloud mode is a shared namespace.

**Scenario B — attacker crafts a key that collides with another org's prefix:**
Not feasible with SHA-256 and 128-bit secrets. This scenario is theoretical only.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:1404-1432`, `signalpilot/gateway/gateway/mcp_auth.py:227-241`
- Endpoints: All MCP endpoints (the auth middleware gates them)
- Auth modes: API key auth in cloud mode

---

## Proposed fix

1. **Include `org_id` as part of the key prefix for defense-in-depth:**

```python
# store.py:create_api_key — include short org_id in prefix:
short_org = oid[:8] if oid and oid != "local" else "local"
prefix = f"sp_{short_org}_{raw_key[:8]}"  # e.g., sp_org_abc1_d4e5f6g7
```

2. **Add periodic integrity reconciliation** (via Clerk webhook handler — see [no-clerk-webhook-signature-verification-handler](no-clerk-webhook-signature-verification-handler-proposal.md)): verify that every `GatewayApiKey.org_id` corresponds to a currently-valid Clerk organization.

3. **Add a startup/scheduled check:**

```python
# Via a management command or startup job:
async def audit_key_org_integrity(session: AsyncSession) -> list[str]:
    """Return key IDs whose org_id is 'local' in cloud mode."""
    result = await session.execute(
        select(GatewayApiKey.id).where(GatewayApiKey.org_id == "local")
    )
    return [row[0] for row in result.all()]
```

4. **Document the trust boundary** explicitly in a comment above `validate_stored_api_key` so future developers understand why the org check ordering matters.

---

## Verification / test plan

**Unit tests:**
1. `test_validate_stored_api_key_wrong_org_not_bypassed` — create key with `org_id="acme"`, attempt validation as `org_id="other"`, assert no cross-org access.
2. `test_key_prefix_includes_org_short_id` — after fix, assert created key prefix includes org segment.

**Manual checklist:**
- Inspect `gateway_api_keys` table for any rows where `org_id IS NULL` or `org_id = 'local'` in a cloud deployment.
- If found, investigate how they were created and rotate them.

---

## Rollout / migration notes

- Changing the key prefix format is a breaking change for existing keys (clients store the full key, not just the prefix, so this is safe — only the DB display prefix changes).
- The DB `prefix` column is for display only; the full hash is used for auth. Old prefix format keys continue to work.
- No key rotation required for existing keys unless `org_id` integrity check reveals misconfigured rows.

**Related findings:** [api-key-storage-allows-user-id-null-and-org-id-null](api-key-storage-allows-user-id-null-and-org-id-null-proposal.md), [org-id-fallback-to-local-in-cloud](org-id-fallback-to-local-in-cloud-proposal.md)
