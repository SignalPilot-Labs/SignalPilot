"""Schema endorsements and PII redaction config, scoped by org_id.

Stateless free-function module mirroring the api_keys / audit_log / projects /
settings pattern.  Store holds thin async delegators; this module owns all logic.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayConnection


async def _get_conn_row(session: AsyncSession, *, org_id: str, name: str) -> GatewayConnection | None:
    result = await session.execute(
        select(GatewayConnection).where(GatewayConnection.org_id == org_id, GatewayConnection.name == name)
    )
    return result.scalar_one_or_none()


async def get_schema_endorsements(session: AsyncSession, *, org_id: str, name: str) -> dict:
    conn = await _get_conn_row(session, org_id=org_id, name=name)
    if not conn or not conn.endorsements:
        return {"endorsed": [], "hidden": [], "mode": "all"}
    return conn.endorsements


async def set_schema_endorsements(session: AsyncSession, *, org_id: str, name: str, endorsements: dict) -> dict:
    conn = await _get_conn_row(session, org_id=org_id, name=name)
    if not conn:
        return {"endorsed": [], "hidden": [], "mode": "all"}
    conn.endorsements = {
        "endorsed": endorsements.get("endorsed", []),
        "hidden": endorsements.get("hidden", []),
        "mode": endorsements.get("mode", "all"),
    }
    await session.commit()
    return conn.endorsements


async def get_pii_config(session: AsyncSession, *, org_id: str, name: str) -> dict:
    conn = await _get_conn_row(session, org_id=org_id, name=name)
    if not conn:
        return {"enabled": False, "rules": {}}
    return {
        "enabled": conn.pii_enabled or False,
        "rules": conn.pii_rules or {},
    }


async def set_pii_config(
    session: AsyncSession, *, org_id: str, name: str, enabled: bool, rules: dict[str, str]
) -> dict:
    conn = await _get_conn_row(session, org_id=org_id, name=name)
    if not conn:
        raise ValueError(f"Connection '{name}' not found")
    conn.pii_enabled = enabled
    conn.pii_rules = rules
    await session.commit()
    return {"enabled": conn.pii_enabled, "rules": conn.pii_rules}


async def delete_schema_endorsements(session: AsyncSession, *, org_id: str, name: str) -> None:
    conn = await _get_conn_row(session, org_id=org_id, name=name)
    if conn:
        conn.endorsements = None
        await session.commit()


async def apply_endorsement_filter(session: AsyncSession, *, org_id: str, name: str, schema: dict) -> dict:
    config = await get_schema_endorsements(session, org_id=org_id, name=name)
    mode = config.get("mode", "all")
    endorsed = set(config.get("endorsed", []))
    hidden = set(config.get("hidden", []))
    if mode == "endorsed_only" and endorsed:
        return {k: v for k, v in schema.items() if k in endorsed}
    if hidden:
        return {k: v for k, v in schema.items() if k not in hidden}
    return schema
