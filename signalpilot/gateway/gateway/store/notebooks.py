"""Notebooks persistence: CRUD operations for notebook metadata, scoped by org_id."""

from __future__ import annotations

import time

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayNotebook
from gateway.models.notebooks import NotebookInfo, NotebookUpload

_MAX_LIMIT = 100


def _row_to_info(row: GatewayNotebook) -> NotebookInfo:
    return NotebookInfo(
        id=row.id,
        name=row.name,
        description=row.description or "",
        tags=row.tags or [],
        cell_count=row.cell_count or 0,
        code_cell_count=row.code_cell_count or 0,
        markdown_cell_count=row.markdown_cell_count or 0,
        kernel_name=row.kernel_name,
        created_at=row.created_at,
        updated_at=row.updated_at,
        analyzed_at=row.analyzed_at,
    )


async def list_notebooks(
    session: AsyncSession,
    *,
    org_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[NotebookInfo]:
    limit = min(limit, _MAX_LIMIT)
    offset = max(offset, 0)
    result = await session.execute(
        select(GatewayNotebook)
        .where(GatewayNotebook.org_id == org_id)
        .order_by(GatewayNotebook.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_row_to_info(r) for r in result.scalars().all()]


async def get_notebook_meta(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
) -> NotebookInfo | None:
    result = await session.execute(
        select(GatewayNotebook).where(
            GatewayNotebook.org_id == org_id,
            GatewayNotebook.id == notebook_id,
        )
    )
    row = result.scalar_one_or_none()
    return _row_to_info(row) if row else None


async def create_notebook(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str | None,
    upload: NotebookUpload,
    notebook_id: str,
    cell_count: int,
    code_cell_count: int,
    markdown_cell_count: int,
    kernel_name: str | None,
) -> NotebookInfo:
    now = time.time()
    row = GatewayNotebook(
        id=notebook_id,
        org_id=org_id,
        user_id=user_id,
        name=upload.name,
        description=upload.description or None,
        tags=upload.tags or [],
        filename=f"{notebook_id}.ipynb",
        cell_count=cell_count,
        code_cell_count=code_cell_count,
        markdown_cell_count=markdown_cell_count,
        kernel_name=kernel_name,
        analysis_json=None,
        created_at=now,
        updated_at=now,
        analyzed_at=None,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        orig = str(e.orig) if e.orig is not None else str(e)
        if "uq_gw_nb_org_name" in orig:
            raise ValueError(f"Notebook '{upload.name}' already exists") from e
        raise
    return _row_to_info(row)


async def update_notebook_analysis(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
    analysis_json: dict,
    analyzed_at: float,
) -> bool:
    result = await session.execute(
        select(GatewayNotebook).where(
            GatewayNotebook.org_id == org_id,
            GatewayNotebook.id == notebook_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    row.analysis_json = analysis_json
    row.analyzed_at = analyzed_at
    row.updated_at = time.time()
    await session.commit()
    return True


async def delete_notebook(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
) -> bool:
    result = await session.execute(
        select(GatewayNotebook).where(
            GatewayNotebook.org_id == org_id,
            GatewayNotebook.id == notebook_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def get_notebook_analysis_json(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
) -> dict | None:
    """Return analysis_json for a notebook, or None if not found / not yet analyzed."""
    result = await session.execute(
        select(GatewayNotebook).where(
            GatewayNotebook.org_id == org_id,
            GatewayNotebook.id == notebook_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    return row.analysis_json


async def search_notebooks(
    session: AsyncSession,
    *,
    org_id: str,
    query: str,
    limit: int = 50,
    offset: int = 0,
) -> list[NotebookInfo]:
    limit = min(limit, _MAX_LIMIT)
    offset = max(offset, 0)
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    result = await session.execute(
        select(GatewayNotebook)
        .where(
            GatewayNotebook.org_id == org_id,
            or_(
                GatewayNotebook.name.ilike(pattern),
                GatewayNotebook.description.ilike(pattern),
                cast(GatewayNotebook.tags, Text).ilike(pattern),
            ),
        )
        .order_by(GatewayNotebook.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_row_to_info(r) for r in result.scalars().all()]
