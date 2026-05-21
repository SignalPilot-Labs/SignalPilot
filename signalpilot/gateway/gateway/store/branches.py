"""Branch and user session CRUD operations."""

from __future__ import annotations

import re
import time
import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayProjectBranch, GatewayUserSession
from ..models.workspace import BranchInfo, UserSessionInfo

_BRANCH_NAME_RE = re.compile(r"^[a-zA-Z0-9/_.\-]{1,200}$")


def _validate_branch_name(name: str) -> str | None:
    if not _BRANCH_NAME_RE.match(name):
        return "Branch name must be 1-200 chars: letters, numbers, / _ - ."
    if ".." in name or name.startswith("/") or name.endswith("/"):
        return "Branch name must not contain '..' or start/end with '/'"
    return None


async def create_branch(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    user_id: str | None,
    name: str,
    from_branch: str = "main",
) -> BranchInfo:
    if err := _validate_branch_name(name):
        raise ValueError(err)
    now = time.time()
    row = GatewayProjectBranch(
        id=str(uuid.uuid4()),
        project_id=project_id,
        org_id=org_id,
        name=name,
        created_from=from_branch,
        is_protected=False,
        is_default=False,
        status="active",
        file_count=0,
        total_bytes=0,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    return _to_branch_info(row)


async def list_branches(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    status: str | None = "active",
) -> list[BranchInfo]:
    q = select(GatewayProjectBranch).where(
        GatewayProjectBranch.org_id == org_id,
        GatewayProjectBranch.project_id == project_id,
    )
    if status:
        q = q.where(GatewayProjectBranch.status == status)
    q = q.order_by(GatewayProjectBranch.is_default.desc(), GatewayProjectBranch.updated_at.desc())
    result = await session.execute(q)
    return [_to_branch_info(r) for r in result.scalars()]


async def get_branch(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    name: str,
) -> BranchInfo | None:
    q = select(GatewayProjectBranch).where(
        GatewayProjectBranch.org_id == org_id,
        GatewayProjectBranch.project_id == project_id,
        GatewayProjectBranch.name == name,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return _to_branch_info(row) if row else None


async def delete_branch(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    name: str,
) -> bool:
    q = select(GatewayProjectBranch).where(
        GatewayProjectBranch.org_id == org_id,
        GatewayProjectBranch.project_id == project_id,
        GatewayProjectBranch.name == name,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        return False
    if row.is_protected:
        raise ValueError(f"Cannot delete protected branch '{name}'")
    row.status = "deleted"
    row.updated_at = time.time()
    await session.commit()
    return True


async def ensure_main_branch(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    user_id: str | None,
) -> BranchInfo:
    """Idempotent: create main branch if it doesn't exist."""
    existing = await get_branch(session, org_id=org_id, project_id=project_id, name="main")
    if existing:
        return existing
    now = time.time()
    row = GatewayProjectBranch(
        id=str(uuid.uuid4()),
        project_id=project_id,
        org_id=org_id,
        name="main",
        created_from=None,
        is_protected=False,
        is_default=True,
        status="active",
        file_count=0,
        total_bytes=0,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    return _to_branch_info(row)


async def get_or_create_user_session(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str,
) -> UserSessionInfo:
    q = select(GatewayUserSession).where(
        GatewayUserSession.org_id == org_id,
        GatewayUserSession.user_id == user_id,
        GatewayUserSession.project_id == project_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if row:
        return UserSessionInfo(
            user_id=row.user_id,
            project_id=row.project_id,
            active_branch=row.active_branch,
            updated_at=row.updated_at,
        )
    now = time.time()
    row = GatewayUserSession(
        id=str(uuid.uuid4()),
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        active_branch="main",
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    return UserSessionInfo(
        user_id=user_id,
        project_id=project_id,
        active_branch="main",
        updated_at=now,
    )


async def update_user_session(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    project_id: str,
    branch_name: str,
) -> UserSessionInfo:
    branch = await get_branch(session, org_id=org_id, project_id=project_id, name=branch_name)
    if not branch or branch.status != "active":
        raise ValueError(f"Branch '{branch_name}' not found or not active")
    q = select(GatewayUserSession).where(
        GatewayUserSession.org_id == org_id,
        GatewayUserSession.user_id == user_id,
        GatewayUserSession.project_id == project_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    now = time.time()
    if row:
        row.active_branch = branch_name
        row.updated_at = now
    else:
        row = GatewayUserSession(
            id=str(uuid.uuid4()),
            org_id=org_id,
            user_id=user_id,
            project_id=project_id,
            active_branch=branch_name,
            updated_at=now,
        )
        session.add(row)
    await session.commit()
    return UserSessionInfo(
        user_id=user_id,
        project_id=project_id,
        active_branch=branch_name,
        updated_at=now,
    )


def _to_branch_info(row: GatewayProjectBranch) -> BranchInfo:
    return BranchInfo(
        id=row.id,
        project_id=row.project_id,
        org_id=row.org_id,
        name=row.name,
        created_from=row.created_from,
        is_protected=row.is_protected,
        is_default=row.is_default,
        status=row.status,
        file_count=row.file_count,
        total_bytes=row.total_bytes,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
