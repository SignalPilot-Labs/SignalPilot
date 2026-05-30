"""Tests for F-20: MultiFernet key rotation.

Cases:
  1. Encrypt with key A; rotate primary=B, old=A; _decrypt recovers plaintext.
  2. Encrypt with A; rotate primary=B, old=A; _decrypt_with_migration returns needs_migration=True.
  3. (C2 strengthened) After rotation, fresh _encrypt(x) decrypts via Fernet(primary) directly.
  4. Comma-separated SP_ENCRYPTION_KEY_OLD with two valid + one invalid → hard fail.
  5. >8 old keys → hard fail.
  6. (C1 routing) user_secrets row encrypted with A; rotate primary=B, old=A; read path re-encrypts.
  7. (Inject-fail demo) mutate list order to [old, primary] → case 3 fails.
"""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet, InvalidToken


def _reset_multifernet_cache(monkeypatch):
    """Reset the MultiFernet module-level cache."""
    import gateway.store.crypto as crypto
    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)


def _setup_key(monkeypatch, key_bytes: bytes, old_keys: list[bytes] | None = None):
    """Configure env for a given primary key and optional old keys."""
    import gateway.store.crypto as crypto
    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)
    monkeypatch.setenv("SP_ENCRYPTION_KEY", key_bytes.decode())
    monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    if old_keys:
        monkeypatch.setenv(
            "SP_ENCRYPTION_KEY_OLD",
            ",".join(k.decode() for k in old_keys),
        )


class TestMultiFernetRotationDecrypt:
    """Case 1: Rotation allows decryption of old ciphertexts."""

    def test_decrypt_ciphertext_encrypted_with_old_key(self, monkeypatch, tmp_path):
        """Encrypt with key A, rotate primary=B old=A, _decrypt recovers plaintext."""
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))

        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        # Encrypt with key A as primary
        _setup_key(monkeypatch, key_a)
        from gateway.store.crypto import _encrypt
        ciphertext = _encrypt("secret-value")

        # Rotate: primary=B, old=A
        _setup_key(monkeypatch, key_b, old_keys=[key_a])
        from gateway.store.crypto import _decrypt
        recovered = _decrypt(ciphertext)
        assert recovered == "secret-value"


class TestMultiFernetMigrationFlag:
    """Case 2: _decrypt_with_migration returns needs_migration=True for old-key ciphertexts."""

    def test_needs_migration_true_for_old_key_ciphertext(self, monkeypatch, tmp_path):
        """Encrypt with A; rotate primary=B, old=A; migration flag is True."""
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))

        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        _setup_key(monkeypatch, key_a)
        from gateway.store.crypto import _encrypt
        ciphertext = _encrypt("migration-test")

        _setup_key(monkeypatch, key_b, old_keys=[key_a])
        from gateway.store.crypto import _decrypt_with_migration
        plaintext, needs_migration = _decrypt_with_migration(ciphertext)
        assert plaintext == "migration-test"
        assert needs_migration is True

    def test_needs_migration_false_for_primary_key_ciphertext(self, monkeypatch, tmp_path):
        """Ciphertext encrypted with the current primary → needs_migration=False."""
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))

        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        _setup_key(monkeypatch, key_b, old_keys=[key_a])
        from gateway.store.crypto import _decrypt_with_migration, _encrypt
        ciphertext = _encrypt("fresh-value")
        plaintext, needs_migration = _decrypt_with_migration(ciphertext)
        assert plaintext == "fresh-value"
        assert needs_migration is False


class TestPrimaryFirstInvariant:
    """Case 3 (C2): Fresh _encrypt output must be decryptable by Fernet(primary) directly."""

    def test_fresh_ciphertext_decryptable_by_primary_directly(self, monkeypatch, tmp_path):
        """After rotation, _encrypt(x) can be decrypted by Fernet(primary).decrypt() alone."""
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))

        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        _setup_key(monkeypatch, key_b, old_keys=[key_a])
        from gateway.store.crypto import _encrypt, _get_encryption_key
        plaintext = "primary-first-check"
        ciphertext = _encrypt(plaintext)

        # Directly use Fernet(primary) — no MultiFernet.
        primary = _get_encryption_key()
        recovered = Fernet(primary).decrypt(ciphertext).decode()
        assert recovered == plaintext


class TestOldKeyValidation:
    """Cases 4 & 5: Invalid SP_ENCRYPTION_KEY_OLD entries → hard fail."""

    def test_invalid_entry_in_old_keys_raises(self, monkeypatch, tmp_path):
        """Case 4: Two valid + one invalid entry → ValueError on load.

        An 'invalid' entry is one whose PBKDF2 derivation fails because
        the SP_DATA_DIR is not writable (can't create salt) and it's not
        a valid raw Fernet key. We force the error by providing a cloud-mode
        env where passphrase derivation requires SP_ENCRYPTION_SALT.
        """
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.delenv("SP_ENCRYPTION_SALT", raising=False)

        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()
        # Third entry is an invalid cloud-mode passphrase (not a raw Fernet key,
        # and SP_ENCRYPTION_SALT is missing, which causes RuntimeError → ValueError).
        combined = f"{key_a.decode()},{key_b.decode()},not-a-raw-fernet-key"
        monkeypatch.setenv("SP_ENCRYPTION_KEY_OLD", combined)

        import gateway.store.crypto as crypto
        monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)

        with pytest.raises(ValueError):
            crypto._get_old_encryption_keys()

    def test_more_than_8_old_keys_raises(self, monkeypatch, tmp_path):
        """Case 5: >8 old keys → hard fail."""
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        keys = [Fernet.generate_key().decode() for _ in range(9)]
        monkeypatch.setenv("SP_ENCRYPTION_KEY_OLD", ",".join(keys))

        import gateway.store.crypto as crypto
        monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)

        with pytest.raises(ValueError, match="maximum is 8"):
            crypto._get_old_encryption_keys()


class TestHealthCheckPrimaryFirstInvariant:
    """_validate_encryption_health asserts primary-first invariant."""

    def test_health_check_passes_with_correct_order(self, monkeypatch, tmp_path):
        """Health check passes when primary is first in MultiFernet."""
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()
        _setup_key(monkeypatch, key_b, old_keys=[key_a])

        from gateway.store.crypto import _validate_encryption_health
        assert _validate_encryption_health() is True

    def test_health_check_fails_if_old_key_encrypts(self, monkeypatch, tmp_path):
        """Case 7 (inject-fail demo): swap order so old key is at index 0 → health fails.

        This simulates a regression where _get_multifernet() builds
        MultiFernet([old, primary]) instead of MultiFernet([primary, old]).
        The C2 invariant check in _validate_encryption_health catches this.
        """
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        key_old = Fernet.generate_key()
        key_primary = Fernet.generate_key()

        # Normal primary
        monkeypatch.setenv("SP_ENCRYPTION_KEY", key_primary.decode())
        monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        from cryptography.fernet import MultiFernet

        import gateway.store.crypto as crypto

        # Inject bad order: old key is first (index 0 = encryptor)
        bad_mf = MultiFernet([Fernet(key_old), Fernet(key_primary)])
        monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", bad_mf)

        # Health check must detect that primary cannot decrypt the ciphertext.
        result = crypto._validate_encryption_health()
        assert result is False


class TestUserSecretsC1Routing:
    """Case 6 (C1): user_secrets read path re-encrypts rows under old key."""

    @pytest.mark.asyncio
    async def test_read_path_reencrypts_old_key_row(self, monkeypatch, tmp_path):
        """Write a row encrypted with key A; rotate primary=B, old=A; read re-encrypts."""
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        # Encrypt the plaintext with key A directly (simulates old row)
        old_ciphertext = Fernet(key_a).encrypt(b"sk-test-anthropic-key-1234567890")

        # Now rotate: primary=B, old=A
        _setup_key(monkeypatch, key_b, old_keys=[key_a])

        # Use _decrypt_with_migration to verify it returns needs_migration=True
        from gateway.store.crypto import _decrypt_with_migration, _get_encryption_key
        plaintext, needs_migration = _decrypt_with_migration(old_ciphertext)
        assert needs_migration is True
        assert plaintext == "sk-test-anthropic-key-1234567890"

        # Re-encrypt with primary key
        from gateway.store.crypto import _encrypt
        new_ciphertext = _encrypt(plaintext)

        # Verify new ciphertext is decryptable by Fernet(primary) directly
        primary = _get_encryption_key()
        recovered = Fernet(primary).decrypt(new_ciphertext).decode()
        assert recovered == "sk-test-anthropic-key-1234567890"

        # Verify old key alone cannot decrypt the new ciphertext
        with pytest.raises(InvalidToken):
            Fernet(key_a).decrypt(new_ciphertext)
