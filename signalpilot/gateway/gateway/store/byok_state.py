"""BYOK provider and DEK cache module-level state."""

from __future__ import annotations

import hashlib
import json
import logging
import threading

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.byok import (
    PROVIDER_TYPE_LOCAL,
    BYOKProvider,
    DEKCache,
    LocalBYOKProvider,
    make_provider_for_key,
)
from gateway.db.models import GatewayBYOKKey, GatewayOrg

logger = logging.getLogger(__name__)

# Module-level BYOK state — set by configure_byok() before any BYOK credentials
# are decrypted. Phase 2 will call configure_byok() from the application lifespan
# handler (main.py startup). Phase 1 only adds the decrypt routing; the globals
# remain None unless explicitly configured.
_byok_provider: BYOKProvider | None = None
_dek_cache: DEKCache | None = None

# Providers built from individual GatewayBYOKKey rows, keyed by the immutable key
# id plus a digest of the row's provider configuration. Access is guarded because
# providers are also built from background tasks.
_provider_cache: dict[str, BYOKProvider] = {}
_provider_cache_lock = threading.Lock()


class BYOKProviderUnavailable(Exception):
    """Raised when no provider can be built for a BYOK key row."""


def configure_byok(provider: BYOKProvider, cache: DEKCache | None = None) -> None:
    """Set the module-level BYOK provider and optional DEK cache.

    Call this during application startup before any requests are served.
    Phase 2 will wire this into the FastAPI lifespan handler in main.py.
    """
    global _byok_provider, _dek_cache
    _byok_provider = provider
    _dek_cache = cache
    invalidate_provider_cache()


def _provider_cache_key(byok_key: GatewayBYOKKey) -> str:
    """Cache key for a key row: immutable id + digest of its provider config.

    The digest means an edited provider_config yields a different entry rather
    than resurrecting a provider pointed at the previous KMS key. Never logged.
    """
    config_blob = json.dumps(byok_key.provider_config or {}, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(f"{byok_key.provider_type}|{config_blob}".encode()).hexdigest()[:32]
    return f"{byok_key.id}:{digest}"


def provider_for_key(byok_key: GatewayBYOKKey) -> BYOKProvider:
    """Return the provider that owns this key row's key material.

    Rows whose provider_type is "local" have no tenant-held KEK: the key material
    lives in the operator's on-disk store, so the configured process-wide provider
    IS the custody boundary and is reused. Every other provider_type is built from
    the row's own configuration so the tenant's KMS key does the wrapping.
    """
    if byok_key.provider_type == PROVIDER_TYPE_LOCAL and isinstance(_byok_provider, LocalBYOKProvider):
        return _byok_provider

    cache_key = _provider_cache_key(byok_key)
    with _provider_cache_lock:
        cached = _provider_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        provider = make_provider_for_key(byok_key)
    except Exception as exc:
        logger.error(
            "Failed to build BYOK provider for key_id=%s provider_type=%s: %s",
            byok_key.id,
            byok_key.provider_type,
            exc,
        )
        raise BYOKProviderUnavailable(
            f"No BYOK provider available for provider_type '{byok_key.provider_type}'"
        ) from exc

    with _provider_cache_lock:
        _provider_cache.setdefault(cache_key, provider)
        return _provider_cache[cache_key]


def invalidate_provider_cache(key_id: str | None = None) -> None:
    """Drop cached providers — all of them, or only those for one key id."""
    with _provider_cache_lock:
        if key_id is None:
            _provider_cache.clear()
            return
        for cache_key in [k for k in _provider_cache if k.split(":", 1)[0] == key_id]:
            del _provider_cache[cache_key]


async def _resolve_byok_key(
    session: AsyncSession,
    org_id: str,
    key_alias: str | None = None,
) -> GatewayBYOKKey | None:
    """Resolve the active BYOK key for an org.

    If key_alias is provided, looks up by org_id + key_alias + status='active'.
    If key_alias is None, looks up the org's default_byok_key_id from GatewayOrg,
    then loads that key.

    Returns the GatewayBYOKKey row or None if not found.
    """
    if key_alias is not None:
        result = await session.execute(
            select(GatewayBYOKKey).where(
                GatewayBYOKKey.org_id == org_id,
                GatewayBYOKKey.key_alias == key_alias,
                GatewayBYOKKey.status == "active",
            )
        )
        return result.scalar_one_or_none()

    # No alias: look up the org's default key
    org_result = await session.execute(select(GatewayOrg).where(GatewayOrg.org_id == org_id))
    org_row = org_result.scalar_one_or_none()
    if org_row is None or not org_row.default_byok_key_id:
        return None

    key_result = await session.execute(
        select(GatewayBYOKKey).where(
            GatewayBYOKKey.id == org_row.default_byok_key_id,
            GatewayBYOKKey.status == "active",
        )
    )
    return key_result.scalar_one_or_none()


async def resolve_decrypt_provider(
    session: AsyncSession,
    org_id: str,
    key_id: str | None,
    key_alias: str | None,
) -> BYOKProvider:
    """Resolve the provider that wrapped an existing credential's DEK.

    Prefers the credential's immutable byok_key_id; falls back to the connection's
    alias. Status is deliberately not filtered — a key mid-rotation must still
    decrypt what it wrapped.
    """
    key_row: GatewayBYOKKey | None = None
    if key_id:
        result = await session.execute(
            select(GatewayBYOKKey).where(
                GatewayBYOKKey.id == key_id,
                GatewayBYOKKey.org_id == org_id,
            )
        )
        key_row = result.scalar_one_or_none()
    if key_row is None and key_alias:
        result = await session.execute(
            select(GatewayBYOKKey).where(
                GatewayBYOKKey.org_id == org_id,
                GatewayBYOKKey.key_alias == key_alias,
            )
        )
        key_row = result.scalars().first()

    if key_row is not None:
        return provider_for_key(key_row)

    # No key row: only the operator-held local store can be the custody boundary.
    if isinstance(_byok_provider, LocalBYOKProvider):
        return _byok_provider
    raise BYOKProviderUnavailable("BYOK key registration not found for this credential")
