"""Credential encryption/decryption using Fernet + PBKDF2.

F-20: MultiFernet rotation support. SP_ENCRYPTION_KEY_OLD (comma-separated)
holds previous keys. Primary key (SP_ENCRYPTION_KEY) is always first in the
MultiFernet list: index 0 is the encrypt key.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets

import gateway.store._atomic as _atomic
import gateway.store._constants as _constants

logger = logging.getLogger(__name__)

_MAX_OLD_KEYS = 8


class CredentialEncryptionError(Exception):
    """Raised when credential encryption or decryption fails in a non-recoverable way."""


# Module-level key cache: populated on first call, reused thereafter.
# Avoids re-running PBKDF2 (≈200 ms) on every encrypt/decrypt call.
_CACHED_MULTIFERNET: object | None = None  # type: MultiFernet | None


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


def _resolve_key_bytes(key_str: str) -> bytes:
    """Resolve a key string to raw Fernet key bytes.

    Accepts either a raw Fernet key (validated via Fernet constructor) or a
    passphrase (derived via PBKDF2). Raises ValueError on invalid raw-key format
    that is also too short to be a passphrase.
    """
    from cryptography.fernet import Fernet

    from gateway.runtime.mode import is_cloud_mode

    try:
        Fernet(key_str.encode())
        return key_str.encode()
    except Exception:
        pass

    # Passphrase path
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
        return base64.urlsafe_b64encode(kdf.derive(key_str.encode()))
    return _derive_key_pbkdf2(key_str)


def _get_encryption_key() -> bytes:
    """Return the primary Fernet key bytes (for invariant checks and health check).

    Does NOT use the MultiFernet cache: always returns the primary key directly.
    This function is the single source of truth for the primary-first invariant.
    """
    from cryptography.fernet import Fernet

    from gateway.runtime.mode import is_cloud_mode

    key_str = os.getenv("SP_ENCRYPTION_KEY")
    if key_str:
        return _resolve_key_bytes(key_str)
    if is_cloud_mode():
        raise RuntimeError(
            "SP_ENCRYPTION_KEY environment variable is required in cloud mode. "
            "Cannot auto-generate encryption key from filesystem."
        )
    key_file = _constants.DATA_DIR / _constants.KEY_FILE_NAME
    _constants.DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    return _atomic._atomic_create_file(key_file, key).strip()


def _get_old_encryption_keys() -> list[bytes]:
    """Return list of old key bytes from SP_ENCRYPTION_KEY_OLD (comma-separated).

    Each entry is validated via the same passphrase-or-raw-Fernet path as the primary.
    Raises ValueError on any invalid entry. Raises ValueError if more than 8 entries.
    """
    raw = os.getenv(_constants.OLD_ENCRYPTION_KEY_ENV, "")
    if not raw.strip():
        return []

    entries = [e.strip() for e in raw.split(",") if e.strip()]
    if len(entries) > _MAX_OLD_KEYS:
        raise ValueError(
            f"SP_ENCRYPTION_KEY_OLD has {len(entries)} entries; maximum is {_MAX_OLD_KEYS}. "
            "Remove keys that are no longer needed for decryption."
        )

    result: list[bytes] = []
    for i, entry in enumerate(entries):
        try:
            result.append(_resolve_key_bytes(entry))
        except Exception as exc:
            raise ValueError(
                f"SP_ENCRYPTION_KEY_OLD entry {i + 1} is invalid: {exc}"
            ) from exc
    return result


def _get_multifernet() -> object:  # -> MultiFernet
    """Return the cached MultiFernet instance.

    Primary key is ALWAYS first (index 0): MultiFernet encrypts with the first
    key in the list. Old keys follow for decryption fallback only.
    """
    global _CACHED_MULTIFERNET
    if _CACHED_MULTIFERNET is not None:
        return _CACHED_MULTIFERNET

    from cryptography.fernet import Fernet, MultiFernet

    primary = _get_encryption_key()
    old_keys = _get_old_encryption_keys()
    _CACHED_MULTIFERNET = MultiFernet([Fernet(primary), *[Fernet(k) for k in old_keys]])
    return _CACHED_MULTIFERNET


def _encrypt(data: str) -> bytes:
    from cryptography.fernet import MultiFernet

    mf: MultiFernet = _get_multifernet()  # type: ignore[assignment]
    return mf.encrypt(data.encode())


def _decrypt(encrypted: bytes) -> str:
    from cryptography.fernet import MultiFernet

    mf: MultiFernet = _get_multifernet()  # type: ignore[assignment]
    return mf.decrypt(encrypted).decode()


def _decrypted_with_primary(token: bytes) -> str | None:
    """Try to decrypt token using ONLY the primary key.

    Returns the plaintext if the primary key decrypts successfully,
    None if the primary key cannot decrypt this token (it was encrypted
    with an old key and migration is needed).
    """
    from cryptography.fernet import Fernet, InvalidToken

    primary = _get_encryption_key()
    try:
        return Fernet(primary).decrypt(token).decode()
    except InvalidToken:
        return None


def _decrypt_with_migration(encrypted: bytes) -> tuple[str, bool]:
    """Decrypt ciphertext, following the key-rotation chain.

    MultiFernet accepts the primary key and SP_ENCRYPTION_KEY_OLD.
    Rewrite ciphertext with the primary key after decryption uses the secondary rotation key.
    Re-encrypt ciphertext from unsupported key derivations before key retirement.

    Returns:
        (plaintext, needs_migration) where needs_migration is True when the
        ciphertext was NOT encrypted with the current primary key.
    """
    # The primary key alone first: if it decrypts, nothing needs rewriting.
    primary_result = _decrypted_with_primary(encrypted)
    if primary_result is not None:
        return primary_result, False

    # The caller rewrites ciphertext after SP_ENCRYPTION_KEY_OLD decrypts it.
    try:
        plaintext = _decrypt(encrypted)
    # A successful MultiFernet result after primary failure identifies the secondary rotation key.
        logger.warning(
            "Credential decrypted with an old key (MultiFernet fallback). "
            "Row will be re-encrypted with the primary key."
        )
        return plaintext, True
    except Exception:
        pass

    raise CredentialEncryptionError("Credential decryption failed; token is invalid.")


def _validate_encryption_health() -> bool:
    """Verify that the current encryption key can round-trip encrypt/decrypt.

    F-20 C2: Also asserts the primary-first invariant: the fresh ciphertext
    MUST be decryptable by Fernet(primary) directly (not via MultiFernet). Any
    regression that places an old key at index 0 in _get_multifernet() will fail
    this check at startup.

    Returns True if healthy, False otherwise. Called at startup.
    """
    from cryptography.fernet import Fernet

    try:
        test_plaintext = "health-check-" + secrets.token_hex(8)
        ciphertext = _encrypt(test_plaintext)
        # Standard round-trip via MultiFernet.
        recovered = _decrypt(ciphertext)
        if recovered != test_plaintext:
            return False
        # Primary-first invariant: Fernet(primary) MUST decrypt the ciphertext directly.
        primary = _get_encryption_key()
        primary_recovered = Fernet(primary).decrypt(ciphertext).decode()
        if primary_recovered != test_plaintext:
            logger.error(
                "Encryption health check: primary-first invariant FAILED. "
                "The primary key is not at index 0 in MultiFernet. "
                "Check _get_multifernet() key order."
            )
            return False
        return True
    except Exception as exc:
        logger.error("Encryption health check failed: %s", exc)
        return False
