"""Org policy for personal connectors (R4)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayMcpOrgPolicy
from gateway.store.mcp._common import iso, utcnow


async def get_policy(session: AsyncSession, *, org_id: str) -> GatewayMcpOrgPolicy | None:
    return (
        await session.execute(select(GatewayMcpOrgPolicy).where(GatewayMcpOrgPolicy.org_id == org_id))
    ).scalar_one_or_none()


async def upsert_policy(
    session: AsyncSession, *, org_id: str, allow_personal: bool, allowed_hosts: list[str]
) -> GatewayMcpOrgPolicy:
    row = await get_policy(session, org_id=org_id)
    if row is None:
        row = GatewayMcpOrgPolicy(org_id=org_id)
        session.add(row)
    row.allow_personal = allow_personal
    row.allowed_hosts_json = [host.strip().lower() for host in allowed_hosts if host.strip()]
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return row


def policy_to_dict(row: GatewayMcpOrgPolicy | None) -> dict:
    if row is None:
        return {"allow_personal": True, "allowed_hosts": [], "updated_at": None}
    return {
        "allow_personal": bool(row.allow_personal),
        "allowed_hosts": list(row.allowed_hosts_json or []),
        "updated_at": iso(row.updated_at),
    }
