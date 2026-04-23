"""BYOK (Bring Your Own Key) envelope encryption foundation.

Provides:
- BYOKProvider protocol: async interface for key wrapping/unwrapping
- LocalBYOKProvider: Fernet-based implementation for testing and development
- DEKCache: thread-safe TTL cache for plaintext DEKs (avoids redundant KMS calls)
- encrypt_envelope / decrypt_envelope: envelope encryption helpers used by store.py
- encrypt_fields_envelope: multi-field single-DEK encryption helper
- migrate_to_byok / revert_to_managed: credential migration functions

Dependency direction: this module depends on nothing within the project
except db.models (data layer — not a circular dependency).
External dependency: cryptography (already a project dependency).

Security note: DEKCache stores plaintext DEKs in memory. The TTL is a
security-sensitive parameter — keep it short. Clear the cache on shutdown.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db.models import GatewayConnection, GatewayCredential

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

DEK_CACHE_DEFAULT_TTL_SECONDS = 300
ENCRYPTION_MODE_MANAGED = "managed"
ENCRYPTION_MODE_BYOK = "byok"


# ─── Exception ───────────────────────────────────────────────────────────────

class BYOKKeyError(Exception):
    """Raised when a key cannot be unwrapped (revoked, deleted, or wrong alias)."""

    def __init__(self, org_id: str, key_alias: str, message: str) -> None:
        super().__init__(message)
        self.org_id = org_id
        self.key_alias = key_alias
        self.message = message


# ─── Protocol ────────────────────────────────────────────────────────────────

@runtime_checkable
class BYOKProvider(Protocol):
    """Async interface for key-encryption-key (KEK) management.

    Implementations may delegate to a local Fernet key store (LocalBYOKProvider),
    AWS KMS, GCP Cloud KMS, or Azure Key Vault (Phase 2+).
    """

    async def wrap_dek(self, org_id: str, key_alias: str, dek_plaintext: bytes) -> bytes:
        """Encrypt a DEK using the org's KEK. Returns wrapped (encrypted) DEK bytes."""
        ...

    async def unwrap_dek(self, org_id: str, key_alias: str, wrapped_dek: bytes) -> bytes:
        """Decrypt a wrapped DEK back to plaintext. Raises BYOKKeyError on failure."""
        ...

    async def generate_dek(self) -> bytes:
        """Generate a fresh Fernet key (44 bytes). Used as the DEK for envelope encryption."""
        ...

    async def health_check(self) -> bool:
        """Return True if the provider backend is reachable."""
        ...


# ─── LocalBYOKProvider ───────────────────────────────────────────────────────

class LocalBYOKProvider:
    """Fernet-based BYOK provider for testing and local development.

    Keys are stored in memory only. Not suitable for production use.
    Each key in `_keys` is a Fernet-format key (44-byte base64url-encoded string
    as returned by Fernet.generate_key()).
    """

    def __init__(self) -> None:
        # Maps "{org_id}:{key_alias}" -> Fernet-format key bytes (44 bytes)
        self._keys: dict[str, bytes] = {}

    def register_key(self, org_id: str, key_alias: str, key: bytes | None = None) -> None:
        """Register a KEK for the given org and alias.

        If key is None, generate a new Fernet key. This is a sync method for
        test setup convenience.
        """
        slot = f"{org_id}:{key_alias}"
        self._keys[slot] = key if key is not None else Fernet.generate_key()

    def revoke_key(self, org_id: str, key_alias: str) -> None:
        """Remove a KEK. Subsequent unwrap calls for this key raise BYOKKeyError."""
        slot = f"{org_id}:{key_alias}"
        self._keys.pop(slot, None)

    def _get_fernet(self, org_id: str, key_alias: str) -> Fernet:
        slot = f"{org_id}:{key_alias}"
        kek = self._keys.get(slot)
        if kek is None:
            raise BYOKKeyError(
                org_id=org_id,
                key_alias=key_alias,
                message=f"Key not found for org={org_id!r} alias={key_alias!r}",
            )
        return Fernet(kek)

    async def wrap_dek(self, org_id: str, key_alias: str, dek_plaintext: bytes) -> bytes:
        """Encrypt a DEK using the registered KEK. Returns Fernet ciphertext bytes."""
        f = self._get_fernet(org_id, key_alias)
        return f.encrypt(dek_plaintext)

    async def unwrap_dek(self, org_id: str, key_alias: str, wrapped_dek: bytes) -> bytes:
        """Decrypt a wrapped DEK. Raises BYOKKeyError if key missing or token invalid."""
        f = self._get_fernet(org_id, key_alias)
        try:
            return f.decrypt(wrapped_dek)
        except InvalidToken as exc:
            raise BYOKKeyError(
                org_id=org_id,
                key_alias=key_alias,
                message=f"Failed to unwrap DEK for org={org_id!r} alias={key_alias!r}: invalid token",
            ) from exc

    async def generate_dek(self) -> bytes:
        """Generate a fresh Fernet key (44 bytes) to use as a DEK."""
        return Fernet.generate_key()

    async def health_check(self) -> bool:
        return True


# ─── DEKCache ─────────────────────────────────────────────────────────────────

class DEKCache:
    """Thread-safe TTL cache for plaintext DEKs.

    Keyed by credential_id (UUID string). Uses monotonic time to avoid
    clock adjustment issues.

    Thread safety note: threading.Lock is used (not asyncio.Lock) because
    the cache may be accessed from both async coroutines and background
    threads (e.g. expiry sweeps). The lock scope is tiny (dict get/put),
    so the small blocking window on the event loop thread is acceptable.

    Security note: entries contain plaintext DEKs. Clear the cache on
    application shutdown to minimise the exposure window.
    """

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        # Maps credential_id -> (dek_plaintext, cached_at_monotonic)
        self._store: dict[str, tuple[bytes, float]] = {}
        self._lock = threading.Lock()

    def get(self, credential_id: str) -> bytes | None:
        """Return the cached DEK if present and not expired, otherwise None."""
        with self._lock:
            entry = self._store.get(credential_id)
            if entry is None:
                return None
            dek, cached_at = entry
            if time.monotonic() - cached_at > self._ttl:
                del self._store[credential_id]
                return None
            return dek

    def put(self, credential_id: str, dek: bytes) -> None:
        """Store a DEK with the current monotonic timestamp."""
        with self._lock:
            self._store[credential_id] = (dek, time.monotonic())

    def invalidate(self, credential_id: str) -> None:
        """Remove a single entry."""
        with self._lock:
            self._store.pop(credential_id, None)

    def clear(self) -> None:
        """Remove all entries. Call on application shutdown."""
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            return {"size": len(self._store), "ttl_seconds": self._ttl}


# ─── Envelope encryption ──────────────────────────────────────────────────────

async def encrypt_envelope(
    provider: BYOKProvider,
    org_id: str,
    key_alias: str,
    plaintext: str,
) -> tuple[bytes, bytes]:
    """Encrypt plaintext using envelope encryption.

    The DEK is a Fernet key generated by provider.generate_dek(). The DEK
    bytes are used directly with Fernet (they are already in Fernet-key format).
    The DEK is then wrapped (encrypted) by the provider's KEK.

    Returns:
        (ciphertext, wrapped_dek) — both as bytes. Store wrapped_dek alongside
        the ciphertext; it is needed for decryption.
    """
    dek: bytes = await provider.generate_dek()
    f = Fernet(dek)
    ciphertext: bytes = f.encrypt(plaintext.encode())
    wrapped_dek: bytes = await provider.wrap_dek(org_id, key_alias, dek)
    return ciphertext, wrapped_dek


async def decrypt_envelope(
    provider: BYOKProvider,
    org_id: str,
    key_alias: str,
    wrapped_dek: bytes,
    ciphertext: bytes,
    cache: DEKCache | None = None,
    credential_id: str | None = None,
) -> str:
    """Decrypt ciphertext using envelope encryption.

    Cache lookup/store is performed when both cache and credential_id are provided.
    The DEK bytes from the cache (or from provider.unwrap_dek) are used directly
    with Fernet — they are Fernet-format keys (44 bytes, base64url-encoded).

    Raises:
        BYOKKeyError: if the key is revoked, missing, or the wrapped DEK is invalid.
    """
    dek: bytes | None = None

    if cache is not None and credential_id is not None:
        dek = cache.get(credential_id)

    if dek is None:
        dek = await provider.unwrap_dek(org_id, key_alias, wrapped_dek)
        if cache is not None and credential_id is not None:
            cache.put(credential_id, dek)

    f = Fernet(dek)
    return f.decrypt(ciphertext).decode()


async def encrypt_fields_envelope(
    provider: BYOKProvider,
    org_id: str,
    key_alias: str,
    fields: list[str],
) -> tuple[list[bytes], bytes]:
    """Encrypt multiple plaintext fields using a single DEK.

    Generates ONE DEK, encrypts each field with it, and wraps the DEK once.
    Use this instead of calling encrypt_envelope() multiple times when you
    need to store multiple ciphertexts with a single wrapped_dek column.

    Returns:
        (list_of_ciphertexts, wrapped_dek) — ciphertexts in the same order as
        the input fields list. Store wrapped_dek alongside all ciphertexts.
    """
    dek: bytes = await provider.generate_dek()
    f = Fernet(dek)
    ciphertexts = [f.encrypt(field.encode()) for field in fields]
    wrapped_dek: bytes = await provider.wrap_dek(org_id, key_alias, dek)
    return ciphertexts, wrapped_dek


async def migrate_to_byok(
    session: AsyncSession,
    provider: BYOKProvider,
    org_id: str,
    key_id: str,
    key_alias: str,
    managed_decrypt: Callable[[bytes], tuple[str, bool]],
) -> tuple[int, int, list[str]]:
    """Re-encrypt all managed credentials for an org's connections to BYOK.

    Loads all eligible credential rows in one query (join with connections),
    then processes each individually. Per-credential atomicity: each row commits
    independently so partial migration is safe to resume.

    Returns:
        (migrated_count, failed_count, error_messages)
    """
    result = await session.execute(
        select(GatewayCredential, GatewayConnection).join(
            GatewayConnection,
            (GatewayConnection.user_id == GatewayCredential.user_id)
            & (GatewayConnection.name == GatewayCredential.connection_name),
        ).where(
            GatewayConnection.org_id == org_id,
            GatewayCredential.encryption_mode == ENCRYPTION_MODE_MANAGED,
        )
    )
    rows = result.all()

    migrated = 0
    failed = 0
    errors: list[str] = []

    for cred_row, conn_row in rows:
        try:
            conn_string_plain, _ = managed_decrypt(cred_row.connection_string_enc)
            extras_plain = "{}"
            if cred_row.extras_enc:
                extras_plain, _ = managed_decrypt(cred_row.extras_enc)

            ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                provider, org_id, key_alias, [conn_string_plain, extras_plain]
            )

            cred_row.connection_string_enc = ciphertexts[0]
            cred_row.extras_enc = ciphertexts[1]
            cred_row.wrapped_dek = wrapped_dek
            cred_row.encryption_mode = ENCRYPTION_MODE_BYOK
            cred_row.byok_key_id = key_id

            conn_row.byok_key_alias = key_alias

            await session.commit()
            migrated += 1
        except Exception:
            await session.rollback()
            logger.exception(
                "Failed to migrate credential for connection '%s' (user '%s')",
                cred_row.connection_name,
                cred_row.user_id,
            )
            error_msg = f"Failed to migrate credential {cred_row.id}: migration error"
            errors.append(error_msg)
            failed += 1

    return migrated, failed, errors


async def revert_to_managed(
    session: AsyncSession,
    provider: BYOKProvider,
    org_id: str,
    managed_encrypt: Callable[[str], bytes],
    cache: DEKCache | None = None,
) -> tuple[int, int, list[str]]:
    """Re-encrypt all BYOK credentials for an org back to managed encryption.

    Loads all eligible credential rows in one query (join with connections),
    then processes each individually. Per-credential atomicity: each row commits
    independently so partial revert is safe.

    Returns:
        (reverted_count, failed_count, error_messages)
    """
    result = await session.execute(
        select(GatewayCredential, GatewayConnection).join(
            GatewayConnection,
            (GatewayConnection.user_id == GatewayCredential.user_id)
            & (GatewayConnection.name == GatewayCredential.connection_name),
        ).where(
            GatewayConnection.org_id == org_id,
            GatewayCredential.encryption_mode == ENCRYPTION_MODE_BYOK,
        )
    )
    rows = result.all()

    migrated = 0
    failed = 0
    errors: list[str] = []

    for cred_row, conn_row in rows:
        try:
            if cred_row.wrapped_dek is None:
                raise ValueError("Credential is BYOK mode but has no wrapped_dek")

            key_alias = conn_row.byok_key_alias
            if not key_alias:
                raise ValueError("Connection is missing byok_key_alias for BYOK decryption")

            conn_string_plain = await decrypt_envelope(
                provider=provider,
                org_id=org_id,
                key_alias=key_alias,
                wrapped_dek=cred_row.wrapped_dek,
                ciphertext=cred_row.connection_string_enc,
                cache=cache,
                credential_id=cred_row.id,
            )

            extras_plain = "{}"
            if cred_row.extras_enc:
                extras_plain = await decrypt_envelope(
                    provider=provider,
                    org_id=org_id,
                    key_alias=key_alias,
                    wrapped_dek=cred_row.wrapped_dek,
                    ciphertext=cred_row.extras_enc,
                    cache=cache,
                    credential_id=cred_row.id,
                )

            cred_row.connection_string_enc = managed_encrypt(conn_string_plain)
            cred_row.extras_enc = managed_encrypt(extras_plain)
            cred_row.wrapped_dek = None
            cred_row.encryption_mode = ENCRYPTION_MODE_MANAGED
            cred_row.byok_key_id = None

            conn_row.byok_key_alias = None

            if cache is not None:
                cache.invalidate(cred_row.id)

            await session.commit()
            migrated += 1
        except Exception:
            await session.rollback()
            logger.exception(
                "Failed to revert credential for connection '%s' (user '%s')",
                cred_row.connection_name,
                cred_row.user_id,
            )
            error_msg = f"Failed to revert credential {cred_row.id}: revert error"
            errors.append(error_msg)
            failed += 1

    return migrated, failed, errors
