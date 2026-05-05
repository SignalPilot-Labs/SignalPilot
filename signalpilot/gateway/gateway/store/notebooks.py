"""Notebooks persistence: CRUD operations for notebook metadata, scoped by org_id."""

from __future__ import annotations

import time
from collections import Counter

from sqlalchemy import Text, case, cast, or_, select
from sqlalchemy import func as sa_func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import ColumnElement

from gateway.db.models import GatewayNotebook
from gateway.models.notebooks import NotebookInfo, NotebookSummary, NotebookUpload

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


async def count_notebooks(
    session: AsyncSession,
    *,
    org_id: str,
) -> int:
    result = await session.execute(
        select(sa_func.count()).select_from(GatewayNotebook).where(GatewayNotebook.org_id == org_id)
    )
    return result.scalar_one()


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


async def update_notebook_metadata(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> NotebookInfo | None:
    result = await session.execute(
        select(GatewayNotebook).where(
            GatewayNotebook.org_id == org_id,
            GatewayNotebook.id == notebook_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    if name is not None:
        row.name = name
    if description is not None:
        row.description = description
    if tags is not None:
        row.tags = tags
    row.updated_at = time.time()
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        orig = str(e.orig) if e.orig is not None else str(e)
        if "uq_gw_nb_org_name" in orig:
            raise ValueError(f"Notebook '{name}' already exists") from e
        raise
    return _row_to_info(row)


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


def _search_filter(query: str, org_id: str) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return (
        GatewayNotebook.org_id == org_id,
        or_(
            GatewayNotebook.name.ilike(pattern),
            GatewayNotebook.description.ilike(pattern),
            cast(GatewayNotebook.tags, Text).ilike(pattern),
        ),
    )


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
    result = await session.execute(
        select(GatewayNotebook)
        .where(*_search_filter(query, org_id))
        .order_by(GatewayNotebook.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_row_to_info(r) for r in result.scalars().all()]


async def count_search_notebooks(
    session: AsyncSession,
    *,
    org_id: str,
    query: str,
) -> int:
    result = await session.execute(
        select(sa_func.count()).select_from(GatewayNotebook).where(*_search_filter(query, org_id))
    )
    return result.scalar_one()


async def get_notebooks_summary(
    session: AsyncSession,
    *,
    org_id: str,
) -> NotebookSummary:
    """Compute aggregate statistics across all notebooks for an org."""

    async def _fetch_aggregate() -> tuple[int, int, int, int, int]:
        result = await session.execute(
            select(
                sa_func.count().label("total_notebooks"),
                sa_func.coalesce(sa_func.sum(GatewayNotebook.cell_count), 0).label("total_cells"),
                sa_func.coalesce(sa_func.sum(GatewayNotebook.code_cell_count), 0).label("total_code_cells"),
                sa_func.coalesce(sa_func.sum(GatewayNotebook.markdown_cell_count), 0).label("total_markdown_cells"),
                sa_func.sum(
                    case((GatewayNotebook.analyzed_at.isnot(None), 1), else_=0)
                ).label("analyzed_count"),
            ).where(GatewayNotebook.org_id == org_id)
        )
        row = result.one()
        return (
            int(row.total_notebooks),
            int(row.total_cells),
            int(row.total_code_cells),
            int(row.total_markdown_cells),
            int(row.analyzed_count or 0),
        )

    async def _fetch_analysis_jsons() -> list[dict]:
        result = await session.execute(
            select(GatewayNotebook.analysis_json).where(
                GatewayNotebook.org_id == org_id,
                GatewayNotebook.analyzed_at.isnot(None),
                GatewayNotebook.analysis_json.isnot(None),
            )
        )
        return [row[0] for row in result.all() if isinstance(row[0], dict)]

    total_notebooks, total_cells, total_code_cells, total_markdown_cells, analyzed_count = (
        await _fetch_aggregate()
    )
    analysis_jsons = await _fetch_analysis_jsons()

    total_code_lines = 0
    notebooks_with_errors = 0
    total_error_cells = 0
    import_counter: Counter[str] = Counter()

    for aj in analysis_jsons:
        total_code_lines += aj.get("total_code_lines", 0)
        error_cells = aj.get("error_cells", [])
        if error_cells:
            notebooks_with_errors += 1
            total_error_cells += len(error_cells)
        for imp in aj.get("imports", []):
            import_counter[imp] += 1

    top_imports = [imp for imp, _ in import_counter.most_common(10)]
    pending_count = total_notebooks - analyzed_count

    return NotebookSummary(
        total_notebooks=total_notebooks,
        total_cells=total_cells,
        total_code_cells=total_code_cells,
        total_markdown_cells=total_markdown_cells,
        total_code_lines=total_code_lines,
        analyzed_count=analyzed_count,
        pending_count=pending_count,
        notebooks_with_errors=notebooks_with_errors,
        total_error_cells=total_error_cells,
        top_imports=top_imports,
    )
