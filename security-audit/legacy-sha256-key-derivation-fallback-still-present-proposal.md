# `_decrypt_with_migration` falls back to bare `sha256(passphrase)` derivation

- Slug: legacy-sha256-key-derivation-fallback-still-present
- Severity: Low
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:253-294`

Back to [issues.md](issues.md)

---

## Problem

`_decrypt_with_migration` includes a fallback to `_derive_key_legacy_sha256` — a bare SHA-256 derivation with no salt and no iterations:

```python
# store.py:253-294
def _decrypt_with_migration(encrypted: bytes) -> tuple[str, bool]:
    # Fast path: try primary key
    try:
        return _decrypt(encrypted), False
    except InvalidToken:
        pass

    # Legacy fallback: bare sha256(passphrase)
    if key_str:
        try:
            Fernet(key_str.encode())
            raise CredentialEncryptionError("...")
        except CredentialEncryptionError:
            raise
        except Exception:
            pass  # It's a passphrase — try legacy

        legacy_key = _derive_key_legacy_sha256(key_str)
        try:
            f_legacy = Fernet(legacy_key)
            plaintext = f_legacy.decrypt(encrypted).decode()
            logger.warning("Credential decrypted with legacy SHA-256 key derivation...")
            return plaintext, True  # needs_migration=True
        except InvalidToken:
            pass
```

The bare SHA-256 derivation is:
- No salt
- No iterations
- Single SHA-256 hash of the passphrase

This is equivalent to using the passphrase as an encryption key, which is trivially crackable for any passphrase shorter than ~256 bits of entropy. A dictionary attack against a leaked DB + bare SHA-256 key derivation is feasible on commodity hardware.

The function is intended to be temporary — row is re-encrypted on migration. But "temporary" legacy paths in production codebases tend to persist indefinitely.

---

## Impact

- If any credentials are still encrypted with the legacy SHA-256 key, they are weaker than PBKDF2-derived credentials.
- An attacker with a DB dump and the passphrase (or a dictionary attack) can decrypt credentials that have not yet been migrated.
- The legacy path increases code complexity and creates an additional attack surface for timing attacks.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:253-294`
- Endpoints: All credential decryption paths
- Auth modes: Cloud and local

---

## Proposed fix

1. **Add a startup metric** that counts rows still on the legacy scheme:

```python
# main.py:lifespan:
legacy_count = await _count_legacy_encrypted_rows(session)
if legacy_count > 0:
    logger.warning(
        "STARTUP: %d credentials still encrypted with legacy SHA-256 scheme. "
        "These will be migrated on next access. "
        "Once count reaches zero, the legacy fallback can be removed.",
        legacy_count
    )
    metrics.gauge("signalpilot.crypto.legacy_row_count", legacy_count)
```

2. **Remove the legacy branch** once the count reaches zero in production:

After verifying `legacy_row_count == 0` across all environments for at least 30 days, remove the `_derive_key_legacy_sha256` call from `_decrypt_with_migration`.

3. **In cloud mode, refuse to start if legacy rows exist**:

```python
if is_cloud_mode() and legacy_count > 0:
    raise RuntimeError(
        f"Cannot start in cloud mode: {legacy_count} credentials use legacy "
        "SHA-256 encryption. Run the migration job first."
    )
```

This forces migration before cloud deployment.

---

## Verification / test plan

**Unit tests:**
1. `test_legacy_migration_triggered_on_decrypt` — row encrypted with legacy key, assert `needs_migration=True` returned.
2. `test_legacy_count_zero_allows_startup` — legacy count = 0, cloud mode, assert startup succeeds.
3. `test_legacy_count_nonzero_fails_startup_cloud` — legacy count > 0, cloud mode, assert `RuntimeError`.

**Manual checklist:**
- Check `SELECT COUNT(*) FROM gateway_connections WHERE encryption_mode = 'legacy'` (or equivalent column).
- Run the migration: decrypt and re-encrypt all legacy rows.
- Verify count reaches zero.
- Deploy the version without the legacy fallback.

---

## Rollout / migration notes

- **Order of operations:**
  1. Deploy with legacy fallback still present + startup warning.
  2. Run migration job (triggers on credential access or explicitly via admin endpoint).
  3. Verify legacy count = 0.
  4. Deploy version without legacy fallback.
- Rollback: restore the `_derive_key_legacy_sha256` fallback.

**Related findings:** [sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt](sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt-proposal.md)
