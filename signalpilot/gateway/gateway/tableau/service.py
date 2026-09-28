"""Glue between the org integration row and the Tableau client."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.store import tableau as tableau_store

from .client import TableauClient, TableauCredentials, TableauError

# Tests replace this with an ``httpx.MockTransport``.
transport_override: httpx.AsyncBaseTransport | None = None


def make_client(creds: TableauCredentials, *, cache_key: str | None) -> TableauClient:
    return TableauClient(creds, cache_key=cache_key, transport=transport_override)


@dataclass(frozen=True)
class VerifiedSite:
    site_id: str
    user_name: str | None
    site_role: str | None


async def verify_credentials(creds: TableauCredentials, *, cache_key: str | None) -> VerifiedSite:
    """Sign in (always fresh) and read the PAT owner. Raises ``TableauError`` on failure.

    A successful sign-in replaces the org's cached token: the PAT has one
    session, so the new token is the only valid one anyway.
    """
    async with make_client(creds, cache_key=cache_key) as client:
        auth = await client.sign_in(force=True)
        user = await client.current_user()
    return VerifiedSite(site_id=auth.site_id, user_name=user.get("name"), site_role=user.get("siteRole"))


async def org_credentials(session: AsyncSession, org_id: str) -> TableauCredentials:
    """Credentials of an ACTIVE integration; ``TableauError(403)`` otherwise."""
    row = await tableau_store.get_integration(session, org_id)
    if not tableau_store.row_is_active(row):
        raise TableauError("The Tableau integration is not active for this organization", status_code=403)
    assert row is not None
    try:
        secret = await tableau_store.decrypt_secret(session, row)
    except Exception:
        raise TableauError("The stored Tableau token cannot be decrypted; reconnect Tableau", status_code=503) from None
    return TableauCredentials(
        server_url=row.server_url,
        site_content_url=row.site_content_url or "",
        pat_name=row.pat_name,
        pat_secret=secret,
    )
