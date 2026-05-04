"""Knowledge Base persistence: CRUD operations scoped by org_id.

All public functions accept an AsyncSession and org_id; the Store class
delegates to these functions via thin wrapper methods.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayKnowledgeDoc, GatewayKnowledgeEdit
from gateway.models.knowledge import (
    KnowledgeDoc,
    KnowledgeDocCreate,
    KnowledgeEdit,
    KnowledgeStatus,
    KnowledgeUsage,
)

# ── Typed exceptions ──────────────────────────────────────────────────────────


class KnowledgeSizeExceeded(Exception):
    """Document body exceeds the hard size cap."""


class KnowledgeOrgQuotaExceeded(Exception):
    """Adding this document would exceed the org's storage quota."""


class KnowledgeDuplicate(Exception):
    """A document with the same unique key already exists."""

    def __init__(self, message: str, existing_id: str | None = None) -> None:
        super().__init__(message)
        self.existing_id = existing_id


class KnowledgeNotFound(Exception):
    """Requested document does not exist or belongs to a different org."""


class KnowledgeStateConflict(Exception):
    """The requested state transition is not valid for the document's current status."""


# ── Auto-accept / review-required category sets ───────────────────────────────

_AUTO_ACCEPT_CATEGORIES = {"decisions", "debugging", "quirks"}
_REVIEW_REQUIRED_CATEGORIES = {"conventions", "domain-rules"}


# ── Internal row → DTO conversion ─────────────────────────────────────────────


def _row_to_doc(row: GatewayKnowledgeDoc, *, include_body: bool) -> KnowledgeDoc:
    return KnowledgeDoc(
        id=row.id,
        org_id=row.org_id,
        scope=row.scope,  # type: ignore[arg-type]
        scope_ref=row.scope_ref,
        category=row.category,  # type: ignore[arg-type]
        title=row.title,
        body=row.body if include_body else None,
        status=row.status,  # type: ignore[arg-type]
        bytes=row.bytes,
        view_count=row.view_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
        updated_by=row.updated_by,
        proposed_by_agent=row.proposed_by_agent,
    )


def _row_to_edit(row: GatewayKnowledgeEdit) -> KnowledgeEdit:
    return KnowledgeEdit(
        id=row.id,
        doc_id=row.doc_id,
        org_id=row.org_id,
        body_before=row.body_before,
        bytes_before=row.bytes_before,
        edited_at=row.edited_at,
        edited_by=row.edited_by,
        edit_kind=row.edit_kind,
    )


# ── Query helpers ──────────────────────────────────────────────────────────────


def _sum_active_bytes(org_id: str):
    """Build a scalar subquery for the org's total active knowledge bytes."""
    return (
        select(func.coalesce(func.sum(GatewayKnowledgeDoc.bytes), 0))
        .where(
            GatewayKnowledgeDoc.org_id == org_id,
            GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
        )
        .scalar_subquery()
    )


async def _find_doc_by_key(
    session: AsyncSession,
    *,
    org_id: str,
    scope: str,
    scope_ref: str | None,
    category: str,
    title: str,
    lock: bool = False,
) -> GatewayKnowledgeDoc | None:
    stmt = select(GatewayKnowledgeDoc).where(
        GatewayKnowledgeDoc.org_id == org_id,
        GatewayKnowledgeDoc.scope == scope,
        GatewayKnowledgeDoc.scope_ref == scope_ref,
        GatewayKnowledgeDoc.category == category,
        GatewayKnowledgeDoc.title == title,
    )
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _trim_history(session: AsyncSession, *, doc_id: str, keep: int) -> None:
    """Delete edit rows beyond the N most recent. No-op when keep == 0."""
    if keep == 0:
        return
    await session.execute(
        text(
            "DELETE FROM gateway_knowledge_edits "
            "WHERE doc_id = :doc_id "
            "AND id NOT IN ("
            "  SELECT id FROM gateway_knowledge_edits "
            "  WHERE doc_id = :doc_id "
            "  ORDER BY edited_at DESC "
            "  LIMIT :n"
            ")"
        ),
        {"doc_id": doc_id, "n": keep},
    )


# ── Public CRUD functions ──────────────────────────────────────────────────────


async def list_knowledge_docs(
    session: AsyncSession,
    *,
    org_id: str,
    scope: str | None,
    scope_ref: str | None,
    category: str | None,
    status: str,
    include_body: bool,
    limit: int,
    offset: int,
) -> list[KnowledgeDoc]:
    stmt = select(GatewayKnowledgeDoc).where(GatewayKnowledgeDoc.org_id == org_id)
    if scope is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.scope == scope)
    if scope_ref is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.scope_ref == scope_ref)
    if category is not None:
        stmt = stmt.where(GatewayKnowledgeDoc.category == category)
    if status:
        stmt = stmt.where(GatewayKnowledgeDoc.status == status)
    stmt = stmt.order_by(GatewayKnowledgeDoc.updated_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return [_row_to_doc(r, include_body=include_body) for r in result.scalars().all()]


async def get_knowledge_doc(
    session: AsyncSession,
    *,
    org_id: str,
    doc_id: str,
    include_body: bool,
) -> GatewayKnowledgeDoc | None:
    stmt = select(GatewayKnowledgeDoc).where(
        GatewayKnowledgeDoc.id == doc_id,
        GatewayKnowledgeDoc.org_id == org_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_knowledge_doc_by_key(
    session: AsyncSession,
    *,
    org_id: str,
    scope: str,
    scope_ref: str | None,
    category: str,
    title: str,
) -> GatewayKnowledgeDoc | None:
    return await _find_doc_by_key(
        session,
        org_id=org_id,
        scope=scope,
        scope_ref=scope_ref,
        category=category,
        title=title,
    )


async def insert_knowledge_doc(
    session: AsyncSession,
    *,
    org_id: str,
    payload: KnowledgeDocCreate,
    user_id: str | None,
    agent: str | None,
    limits,
    settings,
) -> KnowledgeDoc:
    """Insert a new knowledge doc. Raises KnowledgeDuplicate on unique-key collision."""
    from gateway.governance.knowledge_limits import check_doc_size, check_org_storage

    scope_val = payload.scope.value
    cat_val = payload.category.value
    body_bytes = len(payload.body.encode("utf-8"))

    check_doc_size(body_bytes)

    # Determine auto-accept vs pending status
    if cat_val in _AUTO_ACCEPT_CATEGORIES:
        status_val = KnowledgeStatus.active.value
    elif cat_val in _REVIEW_REQUIRED_CATEGORIES:
        status_val = KnowledgeStatus.pending.value
    else:
        # e.g. understanding — caller should have rejected; fall back to payload
        status_val = payload.status.value

    now = time.time()
    doc_id = str(uuid.uuid4())

    async with session.begin():
        current_bytes_result = await session.execute(
            select(func.coalesce(func.sum(GatewayKnowledgeDoc.bytes), 0)).where(
                GatewayKnowledgeDoc.org_id == org_id,
                GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
            )
        )
        current_bytes = current_bytes_result.scalar() or 0
        new_bytes = body_bytes if status_val == KnowledgeStatus.active.value else 0
        check_org_storage(current_bytes, new_bytes, 0, limits)

        row = GatewayKnowledgeDoc(
            id=doc_id,
            org_id=org_id,
            scope=scope_val,
            scope_ref=payload.scope_ref,
            category=cat_val,
            title=payload.title,
            body=payload.body,
            status=status_val,
            bytes=body_bytes,
            view_count=0,
            created_at=now,
            updated_at=now,
            created_by=user_id,
            updated_by=user_id,
            proposed_by_agent=agent,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            # Find existing doc ID for the duplicate-key message
            existing = await _find_doc_by_key(
                session,
                org_id=org_id,
                scope=scope_val,
                scope_ref=payload.scope_ref,
                category=cat_val,
                title=payload.title,
            )
            raise KnowledgeDuplicate(
                f"Knowledge doc '{payload.title}' already exists at {scope_val}:{payload.scope_ref}",
                existing_id=existing.id if existing else None,
            ) from exc

    await session.refresh(row)
    return _row_to_doc(row, include_body=True)


async def upsert_knowledge_doc(
    session: AsyncSession,
    *,
    org_id: str,
    payload: KnowledgeDocCreate,
    user_id: str | None,
    agent: str | None,
    limits,
    settings,
) -> KnowledgeDoc:
    """Insert or update by unique key. On update, appends an edit row and trims history."""
    from gateway.governance.knowledge_limits import check_doc_size, check_org_storage, effective_history_versions

    scope_val = payload.scope.value
    cat_val = payload.category.value
    body_bytes = len(payload.body.encode("utf-8"))

    check_doc_size(body_bytes)

    now = time.time()

    async with session.begin():
        existing = await _find_doc_by_key(
            session,
            org_id=org_id,
            scope=scope_val,
            scope_ref=payload.scope_ref,
            category=cat_val,
            title=payload.title,
            lock=True,
        )

        current_bytes_result = await session.execute(
            select(func.coalesce(func.sum(GatewayKnowledgeDoc.bytes), 0)).where(
                GatewayKnowledgeDoc.org_id == org_id,
                GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
            )
        )
        current_bytes = current_bytes_result.scalar() or 0
        old_bytes = existing.bytes if existing else 0
        check_org_storage(current_bytes, body_bytes, old_bytes, limits)

        if existing is None:
            # Insert path
            if cat_val in _AUTO_ACCEPT_CATEGORIES:
                status_val = KnowledgeStatus.active.value
            elif cat_val in _REVIEW_REQUIRED_CATEGORIES:
                status_val = KnowledgeStatus.pending.value
            else:
                status_val = payload.status.value

            doc_id = str(uuid.uuid4())
            row = GatewayKnowledgeDoc(
                id=doc_id,
                org_id=org_id,
                scope=scope_val,
                scope_ref=payload.scope_ref,
                category=cat_val,
                title=payload.title,
                body=payload.body,
                status=status_val,
                bytes=body_bytes,
                view_count=0,
                created_at=now,
                updated_at=now,
                created_by=user_id,
                updated_by=user_id,
                proposed_by_agent=agent,
            )
            session.add(row)
            await session.flush()
            doc_id = row.id
        else:
            # Update path — append edit row, update doc
            edit = GatewayKnowledgeEdit(
                id=str(uuid.uuid4()),
                doc_id=existing.id,
                org_id=org_id,
                body_before=existing.body,
                bytes_before=existing.bytes,
                edited_at=now,
                edited_by=user_id or agent,
                edit_kind="human" if agent is None else "agent",
            )
            session.add(edit)

            existing.body = payload.body
            existing.bytes = body_bytes
            existing.updated_at = now
            existing.updated_by = user_id
            await session.flush()

            keep = effective_history_versions(limits, settings)
            await _trim_history(session, doc_id=existing.id, keep=keep)
            doc_id = existing.id

    row_result = await session.execute(
        select(GatewayKnowledgeDoc).where(
            GatewayKnowledgeDoc.id == doc_id,
            GatewayKnowledgeDoc.org_id == org_id,
        )
    )
    final_row = row_result.scalar_one()
    return _row_to_doc(final_row, include_body=True)


async def update_knowledge_body(
    session: AsyncSession,
    *,
    org_id: str,
    doc_id: str,
    body: str,
    user_id: str | None,
    agent: str | None,
    limits,
    settings,
) -> KnowledgeDoc:
    """Update document body, append edit row, trim history."""
    from gateway.governance.knowledge_limits import check_doc_size, check_org_storage, effective_history_versions

    body_bytes = len(body.encode("utf-8"))
    check_doc_size(body_bytes)

    now = time.time()

    async with session.begin():
        result = await session.execute(
            select(GatewayKnowledgeDoc)
            .where(
                GatewayKnowledgeDoc.id == doc_id,
                GatewayKnowledgeDoc.org_id == org_id,
            )
            .with_for_update()
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise KnowledgeNotFound(f"Knowledge doc '{doc_id}' not found")

        current_bytes_result = await session.execute(
            select(func.coalesce(func.sum(GatewayKnowledgeDoc.bytes), 0)).where(
                GatewayKnowledgeDoc.org_id == org_id,
                GatewayKnowledgeDoc.status == KnowledgeStatus.active.value,
            )
        )
        current_bytes = current_bytes_result.scalar() or 0
        check_org_storage(current_bytes, body_bytes, row.bytes, limits)

        edit = GatewayKnowledgeEdit(
            id=str(uuid.uuid4()),
            doc_id=row.id,
            org_id=org_id,
            body_before=row.body,
            bytes_before=row.bytes,
            edited_at=now,
            edited_by=user_id or agent,
            edit_kind="human" if agent is None else "agent",
        )
        session.add(edit)

        row.body = body
        row.bytes = body_bytes
        row.updated_at = now
        row.updated_by = user_id
        await session.flush()

        keep = effective_history_versions(limits, settings)
        await _trim_history(session, doc_id=row.id, keep=keep)

    await session.refresh(row)
    return _row_to_doc(row, include_body=True)


async def archive_knowledge_doc(session: AsyncSession, *, org_id: str, doc_id: str) -> bool:
    """Archive a document (status → 'archived'). Returns False if not found."""
    result = await session.execute(
        select(GatewayKnowledgeDoc).where(
            GatewayKnowledgeDoc.id == doc_id,
            GatewayKnowledgeDoc.org_id == org_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    row.status = KnowledgeStatus.archived.value
    row.updated_at = time.time()
    await session.commit()
    return True


async def approve_knowledge_doc(
    session: AsyncSession, *, org_id: str, doc_id: str, user_id: str | None
) -> KnowledgeDoc:
    """Flip pending → active. Raises KnowledgeNotFound / KnowledgeStateConflict."""
    result = await session.execute(
        select(GatewayKnowledgeDoc).where(
            GatewayKnowledgeDoc.id == doc_id,
            GatewayKnowledgeDoc.org_id == org_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise KnowledgeNotFound(f"Knowledge doc '{doc_id}' not found")
    if row.status != KnowledgeStatus.pending.value:
        raise KnowledgeStateConflict(
            f"Cannot approve doc with status '{row.status}'; only 'pending' docs can be approved"
        )
    row.status = KnowledgeStatus.active.value
    row.updated_at = time.time()
    row.updated_by = user_id
    await session.commit()
    await session.refresh(row)
    return _row_to_doc(row, include_body=True)


async def list_knowledge_edits(
    session: AsyncSession, *, org_id: str, doc_id: str, limit: int
) -> list[KnowledgeEdit]:
    result = await session.execute(
        select(GatewayKnowledgeEdit)
        .where(
            GatewayKnowledgeEdit.doc_id == doc_id,
            GatewayKnowledgeEdit.org_id == org_id,
        )
        .order_by(GatewayKnowledgeEdit.edited_at.desc())
        .limit(limit)
    )
    return [_row_to_edit(r) for r in result.scalars().all()]


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
            (
                GatewayKnowledgeDoc.title.ilike(like_pattern)
                | GatewayKnowledgeDoc.body.ilike(like_pattern)
            ),
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
    except Exception:
        pass
