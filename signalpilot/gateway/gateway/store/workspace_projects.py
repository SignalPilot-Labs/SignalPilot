"""Workspace project CRUD operations."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import GatewayWorkspaceProject
from ..models.workspace import WorkspaceProjectInfo


async def create_project(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
    name: str,
    display_name: str,
    description: str = "",
    source: str = "managed",
    connection_name: str | None = None,
    git_remote: str | None = None,
    tags: list[str] | None = None,
    settings: dict | None = None,
) -> WorkspaceProjectInfo:
    project_id = str(uuid.uuid4())
    now = time.time()
    row = GatewayWorkspaceProject(
        id=project_id,
        org_id=org_id,
        name=name,
        display_name=display_name,
        description=description,
        source=source,
        connection_name=connection_name,
        status="active",
        tags=tags,
        settings=settings,
        git_remote=git_remote,
        file_count=0,
        total_bytes=0,
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()

    # Initialize bare git repo for this project
    try:
        from ..git.repos import clone_from_remote, init_bare_repo
        if source == "github" and git_remote:
            clone_from_remote(project_id, git_remote)
        else:
            init_bare_repo(project_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to init git repo for project %s: %s", project_id, e)

    return _to_info(row)


async def list_projects(
    session: AsyncSession,
    *,
    org_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[WorkspaceProjectInfo], int]:
    base = select(GatewayWorkspaceProject).where(GatewayWorkspaceProject.org_id == org_id)
    if status:
        base = base.where(GatewayWorkspaceProject.status == status)

    total = (await session.execute(select(sa_func.count()).select_from(base.subquery()))).scalar() or 0

    q = base.order_by(GatewayWorkspaceProject.updated_at.desc()).offset(offset).limit(limit)
    result = await session.execute(q)
    return [_to_info(r) for r in result.scalars()], total


async def get_project(
    session: AsyncSession, *, org_id: str, project_id: str
) -> WorkspaceProjectInfo | None:
    q = select(GatewayWorkspaceProject).where(
        GatewayWorkspaceProject.org_id == org_id,
        GatewayWorkspaceProject.id == project_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    return _to_info(row) if row else None


async def update_project(
    session: AsyncSession,
    *,
    org_id: str,
    project_id: str,
    updates: dict,
) -> WorkspaceProjectInfo | None:
    q = select(GatewayWorkspaceProject).where(
        GatewayWorkspaceProject.org_id == org_id,
        GatewayWorkspaceProject.id == project_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        return None
    for k, v in updates.items():
        if v is not None and hasattr(row, k):
            setattr(row, k, v)
    row.updated_at = time.time()
    await session.commit()
    return _to_info(row)


async def delete_project(
    session: AsyncSession, *, org_id: str, project_id: str
) -> bool:
    q = select(GatewayWorkspaceProject).where(
        GatewayWorkspaceProject.org_id == org_id,
        GatewayWorkspaceProject.id == project_id,
    )
    row = (await session.execute(q)).scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.commit()

    # Delete bare git repo
    try:
        from ..git.repos import delete_repo
        delete_repo(project_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to delete git repo for project %s: %s", project_id, e)

    return True


def _to_info(row: GatewayWorkspaceProject) -> WorkspaceProjectInfo:
    return WorkspaceProjectInfo(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        display_name=row.display_name,
        description=row.description,
        source=row.source,
        connection_name=row.connection_name,
        status=row.status,
        tags=row.tags,
        settings=row.settings,
        file_count=row.file_count,
        total_bytes=row.total_bytes,
        default_branch=row.default_branch,
        protected_branches=row.protected_branches,
        git_remote=row.git_remote,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
