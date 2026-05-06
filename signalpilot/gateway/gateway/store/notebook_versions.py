"""Notebook version snapshot persistence: insert and query analysis metric history."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayNotebookVersion
from gateway.models.notebooks import NotebookVersionInfo

_MAX_LIMIT = 100


def _row_to_info(row: GatewayNotebookVersion) -> NotebookVersionInfo:
    return NotebookVersionInfo(
        id=row.id,
        notebook_id=row.notebook_id,
        version_number=row.version_number,
        total_cells=row.total_cells,
        code_cells=row.code_cells,
        markdown_cells=row.markdown_cells,
        error_cells=row.error_cells,
        total_code_lines=row.total_code_lines,
        functions_count=row.functions_count,
        imports_count=row.imports_count,
        analyzed_at=row.analyzed_at,
        created_at=row.created_at,
    )


def _extract_metrics(analysis_json: dict) -> dict[str, int]:
    """Extract scalar metrics from raw analysis JSON."""
    cell_counts: dict[str, int] = analysis_json.get("cell_counts") or {}
    total_cells = sum(cell_counts.values())
    code_cells = cell_counts.get("code", 0)
    markdown_cells = cell_counts.get("markdown", 0)
    error_cells = len(analysis_json.get("error_cells") or [])
    total_code_lines = int(analysis_json.get("total_code_lines") or 0)
    functions_count = len(analysis_json.get("functions_defined") or [])
    imports_count = len(analysis_json.get("imports") or [])
    return {
        "total_cells": total_cells,
        "code_cells": code_cells,
        "markdown_cells": markdown_cells,
        "error_cells": error_cells,
        "total_code_lines": total_code_lines,
        "functions_count": functions_count,
        "imports_count": imports_count,
    }


async def create_version(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
    analysis_json: dict,
    analyzed_at: float,
) -> NotebookVersionInfo:
    """Insert a version snapshot row, auto-incrementing version_number."""
    next_num_result = await session.execute(
        select(sa_func.coalesce(sa_func.max(GatewayNotebookVersion.version_number), 0) + 1).where(
            GatewayNotebookVersion.org_id == org_id,
            GatewayNotebookVersion.notebook_id == notebook_id,
        )
    )
    version_number: int = next_num_result.scalar_one()
    metrics = _extract_metrics(analysis_json)
    row = GatewayNotebookVersion(
        id=str(uuid.uuid4()),
        org_id=org_id,
        notebook_id=notebook_id,
        version_number=version_number,
        total_cells=metrics["total_cells"],
        code_cells=metrics["code_cells"],
        markdown_cells=metrics["markdown_cells"],
        error_cells=metrics["error_cells"],
        total_code_lines=metrics["total_code_lines"],
        functions_count=metrics["functions_count"],
        imports_count=metrics["imports_count"],
        analyzed_at=analyzed_at,
        created_at=time.time(),
    )
    session.add(row)
    await session.commit()
    return _row_to_info(row)


async def list_versions(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
    limit: int,
    offset: int,
) -> list[NotebookVersionInfo]:
    """Return version rows for a notebook, newest first."""
    limit = min(limit, _MAX_LIMIT)
    offset = max(offset, 0)
    stmt = (
        select(GatewayNotebookVersion)
        .where(
            GatewayNotebookVersion.org_id == org_id,
            GatewayNotebookVersion.notebook_id == notebook_id,
        )
        .order_by(GatewayNotebookVersion.version_number.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return [_row_to_info(r) for r in result.scalars().all()]


async def get_version(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
    version_number: int,
) -> NotebookVersionInfo | None:
    """Return a single version row, or None if not found."""
    stmt = select(GatewayNotebookVersion).where(
        GatewayNotebookVersion.org_id == org_id,
        GatewayNotebookVersion.notebook_id == notebook_id,
        GatewayNotebookVersion.version_number == version_number,
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _row_to_info(row)


async def count_versions(
    session: AsyncSession,
    *,
    org_id: str,
    notebook_id: str,
) -> int:
    """Count version rows for pagination."""
    stmt = (
        select(sa_func.count())
        .select_from(GatewayNotebookVersion)
        .where(
            GatewayNotebookVersion.org_id == org_id,
            GatewayNotebookVersion.notebook_id == notebook_id,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one()
