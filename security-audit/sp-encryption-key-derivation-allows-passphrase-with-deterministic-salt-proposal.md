# When `SP_ENCRYPTION_KEY` is a passphrase in cloud mode, salt is derived deterministically from the passphrase via SHA-256

- Slug: sp-encryption-key-derivation-allows-passphrase-with-deterministic-salt
- Severity: Medium
- Cloud impact: Yes
- Confidence: High
- Affected files / endpoints: `signalpilot/gateway/gateway/store.py:212-227`

Back to [issues.md](issues.md)

---

## Problem

When `SP_ENCRYPTION_KEY` is set but is not a valid Fernet key (i.e., it's a passphrase), `_get_encryption_key()` in cloud mode derives the Fernet key using PBKDF2 with a **deterministic salt computed from the passphrase itself**:

```python
# store.py:212-227
if is_cloud_mode():
    deterministic_salt = hashlib.sha256(
        b"signalpilot-cloud-salt:" + key_str.encode()
    ).digest()[:16]
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=PBKDF2_KEY_LENGTH,
        salt=deterministic_salt,  # <-- derived from passphrase, not random
        iterations=PBKDF2_ITERATIONS,
    )
    _CACHED_KEY = base64.urlsafe_b64encode(kdf.derive(key_str.encode()))
```

A salt is supposed to be random and unique per derived key. The purpose of a salt is to prevent two passphrases from deriving the same key and to prevent pre-computation attacks (rainbow tables). Deriving the salt from the passphrase itself defeats both purposes:

1. **Two orgs with the same passphrase produce identical Fernet keys.** In a multi-tenant SaaS, if two separate deployments (e.g., enterprise customer A and enterprise customer B) are both configured with `SP_ENCRYPTION_KEY=companypassword`, they produce the same Fernet key. An attacker who compromises one deployment's encrypted data and knows the passphrase can decrypt the other deployment's data.

2. **Rainbow table pre-computation is possible.** An attacker who knows the `signalpilot-cloud-salt:` prefix can pre-compute Fernet keys for common passphrases.

3. **The correct design is to require a real Fernet key in cloud mode**, not to support passphrases at all. The `_derive_key_legacy_sha256` function handles the local-mode passphrase case.

---

## Impact

- Two cloud deployments with the same passphrase have cross-decryptable encrypted credentials.
- A DB dump combined with the passphrase is sufficient to decrypt all credentials (with enough PBKDF2 iterations, this requires computational work, but the deterministic salt means a rainbow table approach is viable for common passphrases).
- If an attacker compromises one deployment and learns the passphrase, they can decrypt credentials from any other deployment using the same passphrase.

---

## Exploit scenario

1. Enterprise customer A sets `SP_ENCRYPTION_KEY=company-standard-password`.
2. Enterprise customer B (different tenant, same SaaS) sets `SP_ENCRYPTION_KEY=company-standard-password`.
3. Both produce the same Fernet key (deterministic salt → same PBKDF2 output).
4. Attacker compromises Customer A's DB dump and learns the passphrase.
5. Attacker decrypts Customer B's credentials using the same key.

Alternatively:
1. Attacker knows the `signalpilot-cloud-salt:` prefix (public info after this audit).
2. Attacker pre-computes Fernet keys for the top-10,000 corporate passphrases.
3. On compromise of any DB, tries each pre-computed key.

---

## Affected surface

- Files: `signalpilot/gateway/gateway/store.py:212-227`
- Endpoints: All paths that encrypt/decrypt credentials
- Auth modes: Cloud mode (this branch runs only when `is_cloud_mode()`)

---

## Proposed fix

**In cloud mode, refuse passphrases entirely. Require a real Fernet key:**

```python
# store.py:_get_encryption_key() — updated cloud branch:
if is_cloud_mode():
    # Try to use as a Fernet key directly
    try:
        Fernet(key_str.encode())
        _CACHED_KEY = key_str.encode()
        return _CACHED_KEY
    except Exception:
        # It's not a valid Fernet key — reject in cloud mode
        raise RuntimeError(
            "SP_ENCRYPTION_KEY must be a valid Fernet key in cloud mode. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
            "Passphrases are not supported in cloud mode due to deterministic salt risk."
        )
```

This forces operators to generate a proper key at deploy time.

**Migration path for existing deployments using passphrases:**
1. Generate a new Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. Run a migration job that decrypts all credentials with the old passphrase-derived key and re-encrypts with the new Fernet key.
3. Set `SP_ENCRYPTION_KEY` to the new Fernet key.
4. Deploy.

---

## Verification / test plan

**Unit tests:**
1. `test_passphrase_rejected_in_cloud_mode` — `is_cloud_mode=True`, passphrase string, assert `RuntimeError`.
2. `test_fernet_key_accepted_in_cloud_mode` — `is_cloud_mode=True`, valid Fernet key string, assert no error.
3. `test_passphrase_accepted_in_local_mode` — `is_cloud_mode=False`, passphrase, assert PBKDF2 derivation proceeds.

**Manual checklist:**
- Set `SP_ENCRYPTION_KEY=mypassword` and `SP_DEPLOYMENT_MODE=cloud`.
- Start gateway.
- Before fix: starts successfully with deterministic salt. After fix: `RuntimeError` at startup.

---

## Rollout / migration notes

- **Breaking change for cloud deployments using passphrases.** Requires advance communication and a migration window.
- **Order of operations:**
  1. Communicate the deprecation with 30-day notice.
  2. Provide a migration script.
  3. On migration day: decrypt-all, re-encrypt-all with new Fernet key, update env var, deploy.
- **Rollback:** Revert to old code (supports passphrase in cloud mode), keep the new Fernet key but add the legacy path back temporarily.

**Related findings:** [legacy-sha256-key-derivation-fallback-still-present](legacy-sha256-key-derivation-fallback-still-present-proposal.md)
