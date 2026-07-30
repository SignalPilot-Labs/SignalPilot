"""Credential helpers for org-scoped analysis delivery."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.store import org_secrets as org_secrets_store

LOGGER = logging.getLogger(__name__)


async def delivery_api_key_for_org(
    session: AsyncSession,
    *,
    org_id: str,
) -> str:
    """Return the org Anthropic key for delivery rendering, or disable model delivery."""
    try:
        return await org_secrets_store.resolve_anthropic_key(session, org_id) or ""
    except Exception as exc:
        LOGGER.info(
            "Could not load org Anthropic key for analysis delivery; using fallback delivery: %s",
            exc,
        )
        return ""
