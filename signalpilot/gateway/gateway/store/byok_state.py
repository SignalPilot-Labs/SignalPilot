"""BYOK provider and DEK cache module-level state."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.byok import BYOKProvider, DEKCache
from gateway.db.models import GatewayBYOKKey, GatewayOrg

logger = logging.getLogger(__name__)

# Module-level BYOK state — set by configure_byok() before any BYOK credentials
# are decrypted. Phase 2 will call configure_byok() from the application lifespan
# handler (main.py startup). Phase 1 only adds the decrypt routing; the globals
# remain None unless explicitly configured.
_byok_provider: BYOKProvider | None = None
_dek_cache: DEKCache | None = None


def configure_byok(provider: BYOKProvider, cache: DEKCache | None = None) -> None:
    """Set the module-level BYOK provider and optional DEK cache.

    Call this during application startup before any requests are served.
    Phase 2 will wire this into the FastAPI lifespan handler in main.py.
    """
    global _byok_provider, _dek_cache
    _byok_provider = provider
    _dek_cache = cache


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
