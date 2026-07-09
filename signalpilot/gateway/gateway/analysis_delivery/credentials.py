"""Credential helpers for account-scoped analysis delivery."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.store import user_secrets as user_secrets_store

LOGGER = logging.getLogger(__name__)


async def delivery_api_key_for_user(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
) -> str:
    """Return the user's Anthropic key for delivery rendering, or disable model delivery."""
    if not user_id:
        return ""
    try:
        return await user_secrets_store.get_user_anthropic_key(session, org_id, user_id) or ""
    except Exception as exc:
        LOGGER.info(
            "Could not load user Anthropic key for analysis delivery; using fallback delivery: %s",
            exc,
        )
        return ""
