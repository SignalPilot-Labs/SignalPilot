"""Store helpers for org-scoped secrets."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayOrgSecrets
from gateway.store.crypto import _decrypt_with_migration, _encrypt


async def _org_secrets_row(session: AsyncSession, org_id: str) -> GatewayOrgSecrets | None:
    result = await session.execute(select(GatewayOrgSecrets).where(GatewayOrgSecrets.org_id == org_id))
    return result.scalar_one_or_none()


async def get_org_anthropic_key(session: AsyncSession, org_id: str) -> str | None:
    """Return the decrypted org Anthropic API key, if one is stored."""
    row = await _org_secrets_row(session, org_id)
    if not row or not row.anthropic_api_key_enc:
        return None
    try:
        plaintext, needs_migration = _decrypt_with_migration(row.anthropic_api_key_enc)
        if needs_migration:
            row.anthropic_api_key_enc = _encrypt(plaintext)
            await session.commit()
        return plaintext
    except Exception:
        return None


async def set_org_anthropic_key(session: AsyncSession, org_id: str, key: str) -> GatewayOrgSecrets:
    """Store or rotate the org Anthropic API key."""
    row = await _org_secrets_row(session, org_id)
    now = time.time()
    if row is None:
        row = GatewayOrgSecrets(org_id=org_id, updated_at=now)
        session.add(row)
    row.anthropic_api_key_enc = _encrypt(key)
    row.updated_at = now
    await session.commit()
    return row


async def clear_org_anthropic_key(session: AsyncSession, org_id: str) -> GatewayOrgSecrets | None:
    """Clear the org Anthropic API key if an org secret row exists."""
    row = await _org_secrets_row(session, org_id)
    if row is None:
        return None
    row.anthropic_api_key_enc = None
    row.updated_at = time.time()
    await session.commit()
    return row


async def resolve_anthropic_key(session: AsyncSession, org_id: str) -> str | None:
    """Resolve the Anthropic key for analysis. Org secrets are the only source."""
    return await get_org_anthropic_key(session, org_id)
