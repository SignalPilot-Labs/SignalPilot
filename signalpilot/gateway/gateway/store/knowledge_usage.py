"""Knowledge Base persistence: ILIKE search, storage usage and the view counter.

Split from ``gateway/store/knowledge.py`` (the CRUD module) so each stays
readable; the Store mixin delegates to both.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayKnowledgeDoc
from gateway.models.knowledge import KnowledgeDoc, KnowledgeStatus, KnowledgeUsage

from .knowledge import _row_to_doc

logger = logging.getLogger(__name__)


async def search_knowledge(
    session: AsyncSession,
    *,
    org_id: str,
    query: str,
    scope: str | None,
    scope_ref: str | None,
    category: str | None,
    limit: int,
) -> list[KnowledgeDoc]:
    """ILIKE search over title and body. Returns docs with body included."""
    # Sanitize query for ILIKE
    q = query.strip()
    q_escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like_pattern = f"%{q_escaped}%"

    stmt = (
        select(GatewayKnowledgeDoc)
        .where(
            GatewayKnowledgeDoc.org_id == org_id,
            GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
            (GatewayKnowledgeDoc.title.ilike(like_pattern) | GatewayKnowledgeDoc.body.ilike(like_pattern)),
        )
        .order_by(GatewayKnowledgeDoc.updated_at.desc())
        .limit(limit)
    )
    if scope is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.scope == scope)
    if scope_ref is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.scope_ref == scope_ref)
    if category is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.category == category)

    result = await session.execute(stmt)
    return [_row_to_doc(r, include_body=True) for r in result.scalars().all()]


async def get_knowledge_usage(session: AsyncSession, *, org_id: str, limits) -> KnowledgeUsage:
    """Return org-level knowledge storage usage."""
    result = await session.execute(
        select(
            func.count(GatewayKnowledgeDoc.id),
            func.coalesce(func.sum(GatewayKnowledgeDoc.bytes), 0),
        ).where(
            GatewayKnowledgeDoc.org_id == org_id,
            GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
        )
    )
    row = result.one()
    active_docs = row[0]
    active_bytes = row[1] or 0
    storage_limit_mb = limits.knowledge_storage_mb
    storage_limit_bytes = storage_limit_mb * 1024 * 1024 if storage_limit_mb > 0 else 0
    return KnowledgeUsage(
        org_id=org_id,
        active_docs=active_docs,
        active_bytes=active_bytes,
        storage_limit_bytes=storage_limit_bytes,
        storage_limit_mb=storage_limit_mb,
    )


async def increment_knowledge_view(session: AsyncSession, *, org_id: str, doc_id: str) -> None:
    """Best-effort view count increment. Swallows all errors."""
    try:
        await session.execute(
            update(GatewayKnowledgeDoc)
            .where(
                GatewayKnowledgeDoc.id == doc_id,
                GatewayKnowledgeDoc.org_id == org_id,
            )
            .values(view_count=GatewayKnowledgeDoc.view_count + 1)
        )
        await session.commit()
    except Exception as exc:  # best-effort counter — log but do not raise
        logger.debug("increment_knowledge_view failed doc_id=%s exc=%r", doc_id, exc)
