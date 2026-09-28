"""Store helpers for the org-scoped Tableau integration (one row per org).

The PAT secret is Fernet-encrypted with ``gateway.store.crypto`` and is
never part of ``info_dict``.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayTableauIntegration
from gateway.store.crypto import _decrypt_with_migration, _encrypt
from gateway.tableau.urls import site_browser_url


async def get_integration(session: AsyncSession, org_id: str) -> GatewayTableauIntegration | None:
    result = await session.execute(select(GatewayTableauIntegration).where(GatewayTableauIntegration.org_id == org_id))
    return result.scalar_one_or_none()


def row_is_active(row: GatewayTableauIntegration | None) -> bool:
    return bool(row is not None and row.enabled and row.status == "ok")


async def is_active(session: AsyncSession, org_id: str) -> bool:
    """Cheap gate check: one indexed lookup of two columns."""
    result = await session.execute(
        select(GatewayTableauIntegration.enabled, GatewayTableauIntegration.status).where(
            GatewayTableauIntegration.org_id == org_id
        )
    )
    row = result.first()
    return bool(row is not None and row[0] and row[1] == "ok")


async def decrypt_secret(session: AsyncSession, row: GatewayTableauIntegration) -> str:
    """Decrypt the PAT secret, rotating the ciphertext to the primary key when needed."""
    plaintext, needs_migration = _decrypt_with_migration(row.pat_secret_enc)
    if needs_migration:
        row.pat_secret_enc = _encrypt(plaintext)
        await session.commit()
    return plaintext


async def save_integration(
    session: AsyncSession,
    org_id: str,
    *,
    server_url: str,
    site_content_url: str,
    pat_name: str,
    pat_secret: str,
    enabled: bool | None,
    site_id: str | None,
    user_name: str | None,
    site_role: str | None,
    user_id: str | None,
) -> GatewayTableauIntegration:
    """Create or replace the org's integration with freshly verified credentials."""
    row = await get_integration(session, org_id)
    now = time.time()
    if row is None:
        row = GatewayTableauIntegration(org_id=org_id, created_at=now, created_by=user_id, enabled=True)
        session.add(row)
    row.server_url = server_url
    row.site_content_url = site_content_url
    row.pat_name = pat_name
    row.pat_secret_enc = _encrypt(pat_secret)
    if enabled is not None:
        row.enabled = enabled
    row.status = "ok"
    row.last_error = None
    row.site_id = site_id
    row.user_name = user_name
    row.site_role = site_role
    row.verified_at = now
    row.updated_at = now
    await session.commit()
    return row


async def record_check(
    session: AsyncSession,
    row: GatewayTableauIntegration,
    *,
    error: str | None,
    site_id: str | None = None,
    user_name: str | None = None,
    site_role: str | None = None,
) -> GatewayTableauIntegration:
    """Store the result of re-verifying the stored credentials."""
    now = time.time()
    if error:
        row.status = "error"
        row.last_error = error[:2000]
    else:
        row.status = "ok"
        row.last_error = None
        row.site_id = site_id
        row.user_name = user_name
        row.site_role = site_role
        row.verified_at = now
    row.updated_at = now
    await session.commit()
    return row


async def set_enabled(
    session: AsyncSession, row: GatewayTableauIntegration, enabled: bool
) -> GatewayTableauIntegration:
    row.enabled = enabled
    row.updated_at = time.time()
    await session.commit()
    return row


async def delete_integration(session: AsyncSession, org_id: str) -> bool:
    result = await session.execute(delete(GatewayTableauIntegration).where(GatewayTableauIntegration.org_id == org_id))
    await session.commit()
    return bool(result.rowcount)


def info_dict(row: GatewayTableauIntegration | None) -> dict[str, Any]:
    """The ``TableauIntegrationInfo`` shape. Never contains the secret."""
    if row is None:
        return {
            "configured": False,
            "enabled": False,
            "active": False,
            "server_url": None,
            "site_content_url": None,
            "site_url": None,
            "pat_name": None,
            "status": None,
            "last_error": None,
            "user_name": None,
            "site_role": None,
            "verified_at": None,
            "updated_at": None,
        }
    return {
        "configured": True,
        "enabled": bool(row.enabled),
        "active": row_is_active(row),
        "server_url": row.server_url,
        "site_content_url": row.site_content_url or "",
        "site_url": site_browser_url(row.server_url, row.site_content_url or ""),
        "pat_name": row.pat_name,
        "status": row.status or "unknown",
        "last_error": row.last_error,
        "user_name": row.user_name,
        "site_role": row.site_role,
        "verified_at": row.verified_at,
        "updated_at": row.updated_at,
    }
