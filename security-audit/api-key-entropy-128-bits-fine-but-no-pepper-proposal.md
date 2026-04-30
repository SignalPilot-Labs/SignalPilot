# API key hash uses bare SHA-256 (no HMAC/pepper) — DB compromise misses defense-in-depth

- Slug: api-key-entropy-128-bits-fine-but-no-pepper
- Severity: Info
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:1372,1406`, `signalpilot/gateway/gateway/mcp_auth.py:107`

Back to [issues.md](issues.md)

---

## Problem

API key hashing uses bare SHA-256:

```python
# store.py:1372 (create_api_key)
key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

# store.py:1406 (validate_stored_api_key)
key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

# mcp_auth.py:107
key_hash = hashlib.sha256(key.encode()).hexdigest()
```

The raw key is `"sp_" + secrets.token_hex(16)` — 128 bits of entropy. This is not feasible to brute-force (2^128 search space), so the bare SHA-256 is not immediately exploitable.

However, standard practice for API key storage is HMAC-SHA256 with a server-side pepper (`SP_KEY_PEPPER`). Without a pepper:

1. **DB compromise leaks hash comparison targets.** An attacker with read-only DB access gets the SHA-256 hashes. While brute-force against 128-bit secrets is infeasible, dictionary attacks against common prefix patterns (e.g., if keys were ever generated with lower entropy) become possible.
2. **Historical breach correlation.** If the same key was used in another system and hashed differently, cross-system correlation is easier.
3. **No forward secrecy for the hash table.** If the hashing scheme changes in the future, there is no migration path because hashes cannot be verified against an old scheme without the original key.

---

## Impact

- Severity is Info because the 128-bit key space makes brute force infeasible regardless.
- Risk is theoretical: defense-in-depth improvement only.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:1372,1406`, `mcp_auth.py:107`
- Endpoints: Key creation and validation paths
- Auth modes: Cloud and local

---

## Proposed fix

Add HMAC-SHA256 with a server-side pepper:

```python
# store.py — new helper:
import hmac as _hmac_mod

def _hash_api_key(raw_key: str) -> str:
    pepper = os.environ.get("SP_KEY_PEPPER", "")
    if pepper:
        return _hmac_mod.new(
            pepper.encode(), raw_key.encode(), "sha256"
        ).hexdigest()
    # Fall back to bare SHA-256 for backward compatibility
    return hashlib.sha256(raw_key.encode()).hexdigest()
```

Migration: add a `hash_version` column to `GatewayApiKey`. On first successful validation with an old hash, re-hash with pepper and update the row. After all rows are migrated (hash_version == 2), remove the bare SHA-256 fallback.

---

## Verification / test plan

**Unit tests:**
1. `test_hash_api_key_with_pepper` — set `SP_KEY_PEPPER`, assert HMAC hash differs from bare SHA-256.
2. `test_hash_api_key_without_pepper` — no pepper set, assert bare SHA-256 (backward compat).
3. `test_validate_api_key_migration_upgrades_hash` — validate old bare-hash key, assert DB row updated to peppered hash.

---

## Rollout / migration notes

- Set `SP_KEY_PEPPER` to a random 32-byte value at deploy time.
- Existing keys continue to work via backward-compat path until migrated.
- Full migration completes on first use of each key.
- After migration is complete (operationally confirmed), remove the `SP_KEY_PEPPER` absent fallback.
