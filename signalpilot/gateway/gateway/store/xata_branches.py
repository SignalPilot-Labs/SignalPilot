"""Owner records for Xata branches created through the gateway (see db/models/xata.py)."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayXataBranchOwner


async def record_branch_owner(
    session: AsyncSession,
    *,
    org_id: str,
    connection_name: str,
    project: str,
    branch: str,
    user_id: str,
) -> None:
    """Remember that ``user_id`` created ``branch``. Re-creating a name keeps the newest creator."""
    values = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "connection_name": connection_name,
        "project": project,
        "branch": branch,
        "created_by": user_id,
        "created_at": time.time(),
    }
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        statement = pg_insert(GatewayXataBranchOwner).values(**values)
        statement = statement.on_conflict_do_update(
            constraint="uq_gw_xata_branch_owner",
            set_={"created_by": user_id, "created_at": values["created_at"]},
        )
        await session.execute(statement)
    else:
        await session.execute(
            delete(GatewayXataBranchOwner).where(
                GatewayXataBranchOwner.org_id == org_id,
                GatewayXataBranchOwner.connection_name == connection_name,
                GatewayXataBranchOwner.project == project,
                GatewayXataBranchOwner.branch == branch,
            )
        )
        session.add(GatewayXataBranchOwner(**values))
    await session.commit()


async def get_branch_owner(
    session: AsyncSession,
    *,
    org_id: str,
    connection_name: str,
    project: str,
    branch: str,
) -> str | None:
    """The user id that created the branch through the gateway, or None when unknown."""
    return (
        await session.execute(
            select(GatewayXataBranchOwner.created_by).where(
                GatewayXataBranchOwner.org_id == org_id,
                GatewayXataBranchOwner.connection_name == connection_name,
                GatewayXataBranchOwner.project == project,
                GatewayXataBranchOwner.branch == branch,
            )
        )
    ).scalar_one_or_none()


async def forget_branch_owner(
    session: AsyncSession,
    *,
    org_id: str,
    connection_name: str,
    project: str,
    branch: str,
) -> None:
    await session.execute(
        delete(GatewayXataBranchOwner).where(
            GatewayXataBranchOwner.org_id == org_id,
            GatewayXataBranchOwner.connection_name == connection_name,
            GatewayXataBranchOwner.project == project,
            GatewayXataBranchOwner.branch == branch,
        )
    )
    await session.commit()
