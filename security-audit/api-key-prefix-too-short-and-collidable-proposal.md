# API key prefix stored in DB is only 7 chars (`sp_xxxx`); enables enumeration of issued keys

- Slug: api-key-prefix-too-short-and-collidable
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:1378` (`prefix=raw_key[:7]`)

Back to [issues.md](issues.md)

---

## Problem

When an API key is created, only the first 7 characters are stored as the public prefix:

```python
# store.py:1378
db_key = GatewayApiKey(
    ...
    prefix=raw_key[:7],  # e.g., "sp_a1b2" — only 4 chars of entropy after "sp_"
    ...
)
```

The raw key format is `"sp_" + secrets.token_hex(16)` (32 hex chars = 128 bits). The stored prefix is `sp_` plus the first 4 hex characters = 16 bits of public entropy.

Problems:
1. **Birthday collision probability:** With 16 bits of prefix entropy, collisions become likely after ~256 keys in an organization (birthday bound at 2^8 = 256). Admins looking at the key list may see two keys with the same display prefix and incorrectly identify which key was used in an audit log or incident.
2. **Enumeration via prefix:** The prefix is returned by `GET /api/keys` to authenticated admins. While this is admin-scoped, it means an insider threat who compromises an admin account gets a list of 4-char hex prefixes — useful for correlating keys to leaked partial-key artifacts.
3. **Industry baseline:** Stripe uses ≥12-char prefixes (`sk_live_XXXXXXX`). GitHub personal access tokens use format `github_pat_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`. A 7-char prefix (`sp_XXXX`) is below the industry minimum.

---

## Impact

- Low standalone risk since the prefix is only shown to authenticated admins.
- Contributes to insider threat risk: admin-level access reveals more information about key distribution than necessary.
- Collision probability reduces the usefulness of prefixes as unique identifiers in audit logs.

---

## Exploit scenario

Low severity; no direct remote exploit. Admin-insider scenario:

1. Admin account is compromised.
2. Attacker calls `GET /api/keys`, gets list of prefixes: `["sp_a1b2", "sp_a1b2", "sp_c3d4"]`.
3. Two keys have the same 7-char prefix — impossible to distinguish in audit logs.
4. Attacker can correlate a leaked partial key artifact with one of the two collidable keys, reducing the search space.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:1378`
- Endpoints: `GET /api/keys` (admin-scoped display), `POST /api/keys` (creation)
- Auth modes: Cloud and local

---

## Proposed fix

Increase the prefix length to at least 12 characters:

```python
# store.py — in create_api_key:
PREFIX_LENGTH = 12  # Move to constants file
raw_key = "sp_" + secrets.token_hex(16)
prefix = raw_key[:PREFIX_LENGTH]  # "sp_" + 9 hex chars = 36 bits of public entropy

db_key = GatewayApiKey(
    ...
    prefix=prefix,
    ...
)
```

Or adopt a Stripe-style format:
```python
# With environment tier:
env_tag = "live" if is_cloud_mode() else "test"
raw_key = f"sp_{env_tag}_{secrets.token_hex(16)}"
prefix = raw_key[:16]  # "sp_live_XXXXXXXX" — 8 hex chars = 32 bits after prefix
```

Move `PREFIX_LENGTH` to a constants file to avoid magic numbers.

---

## Verification / test plan

**Unit tests:**
1. `test_api_key_prefix_length` — assert created key prefix has at least 12 chars.
2. `test_api_key_prefix_uniqueness` — create 100 keys, assert no prefix collisions (probabilistic — runs quickly with 36-bit entropy).

---

## Rollout / migration notes

- Existing keys in DB retain their 7-char prefix (stored in `prefix` column). This is display-only; the full hash drives authentication. No key rotation needed.
- New keys will have longer prefixes. The UI showing `prefix + "..."` should handle variable-length prefixes.
- No breaking changes.
