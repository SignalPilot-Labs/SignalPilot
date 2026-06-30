"""Reports persistence: CRUD for rendered HTML reports, scoped by org_id.

Reports are hard-deleted (no soft-archive) — deletion is permanent by design.
"""

from __future__ import annotations

import logging
import time
import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayReport
from gateway.models.reports import Report, ReportCreate, ReportSummary

logger = logging.getLogger(__name__)

# Per-report HTML size cap. Reports are rendered in the browser, so keep them
# within a sane bound to protect the DB and the client.
MAX_REPORT_BYTES = 5 * 1024 * 1024  # 5 MB


class ReportSizeExceeded(Exception):
    """Report HTML exceeds the hard size cap."""


class ReportNotFound(Exception):
    """Requested report does not exist or belongs to a different org."""


def _row_to_summary(row: GatewayReport) -> ReportSummary:
    return ReportSummary(
        id=row.id,
        org_id=row.org_id,
        scope_ref=row.scope_ref,
        title=row.title,
        bytes=row.bytes,
        view_count=row.view_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
        proposed_by_agent=row.proposed_by_agent,
    )


def _row_to_report(row: GatewayReport) -> Report:
    return Report(html=row.html, **_row_to_summary(row).model_dump())


async def insert_report(
    session: AsyncSession,
    *,
    org_id: str,
    payload: ReportCreate,
    user_id: str | None,
    agent: str | None,
) -> Report:
    """Insert a new report. Raises ReportSizeExceeded when the HTML is too large."""
    html_bytes = len(payload.html.encode("utf-8"))
    if html_bytes > MAX_REPORT_BYTES:
        raise ReportSizeExceeded(
            f"Report HTML is {html_bytes} bytes; the limit is {MAX_REPORT_BYTES} bytes"
        )

    now = time.time()
    row = GatewayReport(
        id=str(uuid.uuid4()),
        org_id=org_id,
        scope_ref=payload.scope_ref,
        title=payload.title,
        html=payload.html,
        bytes=html_bytes,
        view_count=0,
        created_at=now,
        updated_at=now,
        created_by=user_id,
        proposed_by_agent=agent,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _row_to_report(row)


async def list_reports(
    session: AsyncSession,
    *,
    org_id: str,
    scope_ref: str | None,
    limit: int,
    offset: int,
) -> list[ReportSummary]:
    stmt = select(GatewayReport).where(GatewayReport.org_id == org_id)
    if scope_ref is not None:
        stmt = stmt.where(GatewayReport.scope_ref == scope_ref)
    stmt = stmt.order_by(GatewayReport.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return [_row_to_summary(r) for r in result.scalars().all()]


async def get_report(
    session: AsyncSession, *, org_id: str, report_id: str
) -> Report | None:
    result = await session.execute(
        select(GatewayReport).where(
            GatewayReport.id == report_id,
            GatewayReport.org_id == org_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return _row_to_report(row)


async def delete_report(session: AsyncSession, *, org_id: str, report_id: str) -> bool:
    """Permanently delete a report. Returns False if it did not exist."""
    result = await session.execute(
        delete(GatewayReport).where(
            GatewayReport.id == report_id,
            GatewayReport.org_id == org_id,
        )
    )
    await session.commit()
    return (result.rowcount or 0) > 0


async def increment_report_view(session: AsyncSession, *, org_id: str, report_id: str) -> None:
    """Best-effort view count increment. Swallows all errors."""
    try:
        await session.execute(
            update(GatewayReport)
            .where(
                GatewayReport.id == report_id,
                GatewayReport.org_id == org_id,
            )
            .values(view_count=GatewayReport.view_count + 1)
        )
        await session.commit()
    except Exception as exc:  # best-effort counter — log but do not raise
        logger.debug("increment_report_view failed report_id=%s exc=%r", report_id, exc)
