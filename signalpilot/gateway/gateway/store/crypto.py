"""Credential encryption/decryption using Fernet + PBKDF2."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets

import gateway.store._atomic as _atomic
import gateway.store._constants as _constants

logger = logging.getLogger(__name__)


class CredentialEncryptionError(Exception):
    """Raised when credential encryption or decryption fails in a non-recoverable way."""


# Module-level key cache — populated on first call, reused thereafter.
# Avoids re-running PBKDF2 (≈200 ms) on every encrypt/decrypt call.
_CACHED_KEY: bytes | None = None


def _load_or_create_salt() -> bytes:
    """Load or create the persistent PBKDF2 salt stored at SP_DATA_DIR/.encryption_salt.

    Uses atomic O_CREAT | O_EXCL to prevent TOCTOU: two simultaneous starts
    cannot each write a different salt and diverge.
    """
    _constants.DATA_DIR.mkdir(parents=True, exist_ok=True)
    salt_file = _constants.DATA_DIR / _constants.SALT_FILE_NAME
    return _atomic._atomic_create_file(salt_file, os.urandom(16))


def _derive_key_pbkdf2(passphrase: str) -> bytes:
    """Derive a Fernet-compatible key from a passphrase using PBKDF2-HMAC-SHA256."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = _load_or_create_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_constants.PBKDF2_KEY_LENGTH,
        salt=salt,
        iterations=_constants.PBKDF2_ITERATIONS,
    )
    raw_key = kdf.derive(passphrase.encode())
    return base64.urlsafe_b64encode(raw_key)


def _derive_key_legacy_sha256(passphrase: str) -> bytes:
    """Legacy (insecure) key derivation via SHA-256. Used only for migration fallback."""
    digest = hashlib.sha256(passphrase.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _derive_key_legacy_cloud_salt(passphrase: str) -> bytes:
    """Legacy cloud-mode derivation with deterministic salt. Migration fallback only.

    This used a salt derived from the passphrase itself, which defeats the
    purpose of salting. Kept only to decrypt rows encrypted before the fix.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    deterministic_salt = hashlib.sha256(b"signalpilot-cloud-salt:" + passphrase.encode()).digest()[:16]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_constants.PBKDF2_KEY_LENGTH,
        salt=deterministic_salt,
        iterations=_constants.PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def _get_encryption_key() -> bytes:
    """Return the cached Fernet key, deriving it on first call."""
    global _CACHED_KEY
    if _CACHED_KEY is not None:
        return _CACHED_KEY

    from cryptography.fernet import Fernet

    from gateway.runtime.mode import is_cloud_mode

    key_str = os.getenv("SP_ENCRYPTION_KEY")
    if key_str:
        try:
            Fernet(key_str.encode())
            # Already a valid Fernet key — use directly.
            _CACHED_KEY = key_str.encode()
            return _CACHED_KEY
        except Exception:
            if is_cloud_mode():
                salt_b64 = os.getenv("SP_ENCRYPTION_SALT")
                if not salt_b64:
                    raise RuntimeError(
                        "SP_ENCRYPTION_SALT is required in cloud mode when "
                        "SP_ENCRYPTION_KEY is a passphrase (not a raw Fernet key). "
                        "Generate one with: python -c "
                        '"import os,base64; print(base64.b64encode(os.urandom(16)).decode())"'
                    )
                salt = base64.b64decode(salt_b64)
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=_constants.PBKDF2_KEY_LENGTH,
                    salt=salt,
                    iterations=_constants.PBKDF2_ITERATIONS,
                )
                _CACHED_KEY = base64.urlsafe_b64encode(kdf.derive(key_str.encode()))
            else:
                _CACHED_KEY = _derive_key_pbkdf2(key_str)
            return _CACHED_KEY
    else:
        if is_cloud_mode():
            raise RuntimeError(
                "SP_ENCRYPTION_KEY environment variable is required in cloud mode. "
                "Cannot auto-generate encryption key from filesystem."
            )
        key_file = _constants.DATA_DIR / _constants.KEY_FILE_NAME
        _constants.DATA_DIR.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        _CACHED_KEY = _atomic._atomic_create_file(key_file, key).strip()
        return _CACHED_KEY


def _encrypt(data: str) -> bytes:
    from cryptography.fernet import Fernet

    f = Fernet(_get_encryption_key())
    return f.encrypt(data.encode())


def _decrypt(encrypted: bytes) -> str:
    from cryptography.fernet import Fernet

    f = Fernet(_get_encryption_key())
    return f.decrypt(encrypted).decode()


def _decrypt_with_migration(encrypted: bytes) -> tuple[str, bool]:
    """Decrypt ciphertext, falling back to legacy key derivation if needed.

    Returns:
        (plaintext, needs_migration) where needs_migration is True when the
        legacy SHA-256 path was used and the caller should re-encrypt the row
        with the current PBKDF2-derived key.
    """
    from cryptography.fernet import Fernet, InvalidToken

    key_str = os.getenv("SP_ENCRYPTION_KEY")

    # Fast path: try primary (PBKDF2-derived or direct Fernet) key first.
    try:
        return _decrypt(encrypted), False
    except InvalidToken:
        pass

    # Only attempt legacy fallback when env var is a passphrase (not a raw Fernet key).
    if key_str:
        try:
            Fernet(key_str.encode())
            # key_str is a valid raw Fernet key — no legacy path makes sense.
            raise CredentialEncryptionError("Credential decryption failed; token is invalid.")
        except CredentialEncryptionError:
            raise
        except Exception:
            pass  # key_str is a passphrase; try legacy derivation.

        # Try legacy cloud-mode derivation (deterministic salt from passphrase).
        legacy_cloud_key = _derive_key_legacy_cloud_salt(key_str)
        try:
            f_cloud = Fernet(legacy_cloud_key)
            plaintext = f_cloud.decrypt(encrypted).decode()
            logger.warning(
                "Credential decrypted with legacy cloud-mode deterministic salt. "
                "This is deprecated — row will be re-encrypted with proper salt."
            )
            return plaintext, True
        except InvalidToken:
            pass

        # Try legacy SHA-256 derivation (no KDF at all).
        if _constants._ALLOW_LEGACY_CRYPTO:
            legacy_key = _derive_key_legacy_sha256(key_str)
            try:
                f_legacy = Fernet(legacy_key)
                plaintext = f_legacy.decrypt(encrypted).decode()
                logger.warning(
                    "Credential decrypted with DEPRECATED legacy SHA-256 key derivation. "
                    "Re-encrypt credentials to remove this dependency. "
                    "Set SP_ALLOW_LEGACY_CRYPTO=false after migration."
                )
                return plaintext, True  # needs_migration=True
            except InvalidToken:
                pass
        else:
            logger.debug("Legacy SHA-256 crypto disabled (SP_ALLOW_LEGACY_CRYPTO=false)")

    raise CredentialEncryptionError("Credential decryption failed; token is invalid.")


def _validate_encryption_health() -> bool:
    """Verify that the current encryption key can round-trip encrypt/decrypt.

    Returns True if healthy, False otherwise. Called at startup.
    """
    try:
        test_plaintext = "health-check-" + secrets.token_hex(8)
        ciphertext = _encrypt(test_plaintext)
        recovered = _decrypt(ciphertext)
        return recovered == test_plaintext
    except Exception as exc:
        logger.error("Encryption health check failed: %s", exc)
        return False
