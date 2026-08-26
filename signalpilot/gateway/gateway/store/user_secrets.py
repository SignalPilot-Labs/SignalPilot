"""Store helpers for per-user secrets."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayUserSecrets
from gateway.store.crypto import _decrypt_with_migration, _encrypt


async def get_user_anthropic_key(session: AsyncSession, org_id: str, user_id: str) -> str | None:
    """Return the decrypted Anthropic API key for a user, if one is stored."""
    result = await session.execute(
        select(GatewayUserSecrets).where(
            GatewayUserSecrets.org_id == org_id,
            GatewayUserSecrets.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
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

