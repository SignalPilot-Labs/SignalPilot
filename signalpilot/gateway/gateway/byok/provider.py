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
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayConnection, GatewayCredential

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
    """Fernet-based BYOK provider for local development.

    Keys are persisted to disk at {data_dir}/byok_keys/{org_id}_{key_alias}.key
    so they survive container restarts. On register, the key is written to disk.
    On access, the key is loaded from disk (cached in memory after first read).
    """

    def __init__(self, data_dir: str | None = None) -> None:
        import os
        from pathlib import Path

        self._data_dir = Path(data_dir or os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot")))
        self._key_dir = self._data_dir / "byok_keys"
        self._key_dir.mkdir(parents=True, exist_ok=True)
        # In-memory cache: "{org_id}:{key_alias}" -> Fernet key bytes
        self._cache: dict[str, bytes] = {}

    def _key_path(self, org_id: str, key_alias: str):
        # Sanitize for filesystem safety
        safe_name = f"{org_id}_{key_alias}".replace("/", "_").replace("\\", "_")
        return self._key_dir / f"{safe_name}.key"

    def register_key(self, org_id: str, key_alias: str, key: bytes | None = None) -> None:
        """Register a KEK. Generates a new Fernet key if none provided. Persists to disk."""
        slot = f"{org_id}:{key_alias}"
        path = self._key_path(org_id, key_alias)
        if path.exists():
            # Key already on disk — load it instead of overwriting
            self._cache[slot] = path.read_bytes().strip()
            return
        key_material = key if key is not None else Fernet.generate_key()
        path.write_bytes(key_material)
        self._cache[slot] = key_material

    def revoke_key(self, org_id: str, key_alias: str) -> None:
        """Remove a KEK from memory and disk."""
        slot = f"{org_id}:{key_alias}"
        self._cache.pop(slot, None)
        path = self._key_path(org_id, key_alias)
        if path.exists():
            path.unlink()

    def _get_fernet(self, org_id: str, key_alias: str) -> Fernet:
        slot = f"{org_id}:{key_alias}"
        kek = self._cache.get(slot)
        if kek is None:
            # Try loading from disk
            path = self._key_path(org_id, key_alias)
            if path.exists():
                kek = path.read_bytes().strip()
                self._cache[slot] = kek
            else:
                raise BYOKKeyError(
                    org_id=org_id,
                    key_alias=key_alias,
                    message="Key not found",
                )
        return Fernet(kek)

    async def wrap_dek(self, org_id: str, key_alias: str, dek_plaintext: bytes) -> bytes:
        f = self._get_fernet(org_id, key_alias)
        return f.encrypt(dek_plaintext)

    async def unwrap_dek(self, org_id: str, key_alias: str, wrapped_dek: bytes) -> bytes:
        f = self._get_fernet(org_id, key_alias)
        try:
            return f.decrypt(wrapped_dek)
        except InvalidToken as exc:
            raise BYOKKeyError(
                org_id=org_id,
                key_alias=key_alias,
                message="Failed to unwrap DEK",
            ) from exc

    async def generate_dek(self) -> bytes:
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

    # Cache key includes org_id to prevent cross-org DEK access (defense-in-depth)
    cache_key = f"{org_id}::{credential_id}" if credential_id else None

    if cache is not None and cache_key is not None:
        dek = cache.get(cache_key)

    if dek is None:
        dek = await provider.unwrap_dek(org_id, key_alias, wrapped_dek)
        if cache is not None and cache_key is not None:
            cache.put(cache_key, dek)

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
        select(GatewayCredential, GatewayConnection)
        .join(
            GatewayConnection,
            (GatewayConnection.org_id == GatewayCredential.org_id)
            & (GatewayConnection.name == GatewayCredential.connection_name),
        )
        .where(
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
                "Failed to migrate credential for connection '%s' (org '%s')",
                cred_row.connection_name,
                conn_row.org_id,
            )
            error_msg = "Failed to migrate a credential: migration error"
            errors.append(error_msg)
            failed += 1

    return migrated, failed, errors


async def rotate_byok_key(
    session: AsyncSession,
    provider: BYOKProvider,
    org_id: str,
    old_key_id: str,
    old_key_alias: str,
    new_key_id: str,
    new_key_alias: str,
    cache: DEKCache | None = None,
) -> tuple[int, int, list[str]]:
    """Re-wrap all DEKs for credentials using old_key_id to new_key_id.

    Loads all eligible BYOK credential rows in one query (join with connections),
    then processes each individually. Per-credential atomicity: each row commits
    independently so partial rotation is safe to resume.

    Returns:
        (rotated_count, failed_count, error_messages)
    """
    result = await session.execute(
        select(GatewayCredential, GatewayConnection)
        .join(
            GatewayConnection,
            (GatewayConnection.org_id == GatewayCredential.org_id)
            & (GatewayConnection.name == GatewayCredential.connection_name),
        )
        .where(
            GatewayConnection.org_id == org_id,
            GatewayCredential.byok_key_id == old_key_id,
            GatewayCredential.encryption_mode == ENCRYPTION_MODE_BYOK,
        )
    )
    rows = result.all()

    rotated = 0
    failed = 0
    errors: list[str] = []

    for cred_row, conn_row in rows:
        try:
            if cred_row.wrapped_dek is None:
                raise ValueError("Credential is BYOK mode but has no wrapped_dek")

            conn_string_plain = await decrypt_envelope(
                provider=provider,
                org_id=org_id,
                key_alias=old_key_alias,
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
                    key_alias=old_key_alias,
                    wrapped_dek=cred_row.wrapped_dek,
                    ciphertext=cred_row.extras_enc,
                    cache=cache,
                    credential_id=cred_row.id,
                )

            ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                provider, org_id, new_key_alias, [conn_string_plain, extras_plain]
            )

            cred_row.connection_string_enc = ciphertexts[0]
            cred_row.extras_enc = ciphertexts[1]
            cred_row.wrapped_dek = wrapped_dek
            cred_row.byok_key_id = new_key_id

            conn_row.byok_key_alias = new_key_alias

            if cache is not None:
                cache.invalidate(cred_row.id)

            await session.commit()
            rotated += 1
        except Exception:
            await session.rollback()
            logger.exception(
                "Failed to rotate credential for connection '%s' (org '%s')",
                cred_row.connection_name,
                conn_row.org_id,
            )
            error_msg = "Failed to rotate a credential: rotation error"
            errors.append(error_msg)
            failed += 1

    return rotated, failed, errors


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
        select(GatewayCredential, GatewayConnection)
        .join(
            GatewayConnection,
            (GatewayConnection.org_id == GatewayCredential.org_id)
            & (GatewayConnection.name == GatewayCredential.connection_name),
        )
        .where(
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
                "Failed to revert credential for connection '%s' (org '%s')",
                cred_row.connection_name,
                conn_row.org_id,
            )
            error_msg = "Failed to revert a credential: revert error"
            errors.append(error_msg)
            failed += 1

    return migrated, failed, errors
