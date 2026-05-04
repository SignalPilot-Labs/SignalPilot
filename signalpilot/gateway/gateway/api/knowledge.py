"""Knowledge Base REST API endpoints.

Admin scope (not write) on mutations is intentional — knowledge requires human
review by design. Do not lower to write without product sign-off.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.knowledge import KnowledgeDoc, KnowledgeDocCreate, KnowledgeDocUpdate, KnowledgeEdit, KnowledgeUsage
from ..security.scope_guard import RequireScope
from ..store.knowledge import (
    KnowledgeDuplicate,
    KnowledgeNotFound,
    KnowledgeOrgQuotaExceeded,
    KnowledgeSizeExceeded,
    KnowledgeStateConflict,
)
from .deps import StoreD

router = APIRouter(prefix="/api")


def _map_knowledge_exc(exc: Exception) -> HTTPException:
    """Map typed knowledge store exceptions to HTTPExceptions."""
    if isinstance(exc, KnowledgeSizeExceeded):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, KnowledgeOrgQuotaExceeded):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, KnowledgeDuplicate):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, KnowledgeNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, KnowledgeStateConflict):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc


@router.get("/knowledge", response_model=list[KnowledgeDoc], dependencies=[RequireScope("read")])
async def list_knowledge(
    store: StoreD,
    scope: str | None = None,
    scope_ref: str | None = None,
    category: str | None = None,
    status: str = "active",
    q: str | None = None,
):
    """List knowledge docs with optional filters. Use ?q= for full-text search."""
    if q is not None:
        q = q.strip()
        if not q:
            raise HTTPException(status_code=422, detail="query parameter 'q' must not be empty after trimming")
        if len(q) > 200:
            raise HTTPException(status_code=422, detail="query parameter 'q' must be <= 200 characters")
        return await store.search_knowledge(
            query=q,
            scope=scope,
            scope_ref=scope_ref,
            category=category,
            limit=200,
            bump_view=False,
        )
    return await store.list_knowledge_docs(
        scope=scope,
        scope_ref=scope_ref,
        category=category,
        status=status,
        include_body=False,
        limit=200,
        offset=0,
    )


@router.get("/knowledge/usage", response_model=KnowledgeUsage, dependencies=[RequireScope("read")])
async def get_knowledge_usage(store: StoreD):
    """Return org-level knowledge storage usage and quota."""
    return await store.get_knowledge_usage()


@router.get(
    "/knowledge/{doc_id}",
    response_model=KnowledgeDoc,
    dependencies=[RequireScope("read")],
)
async def get_knowledge_doc(doc_id: str, store: StoreD):
    """Get a single knowledge doc by ID, including body."""
    doc = await store.get_knowledge_doc(doc_id, include_body=True, bump_view=True)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Knowledge doc '{doc_id}' not found")
    return doc


@router.post(
    "/knowledge",
    response_model=KnowledgeDoc,
    status_code=201,
    dependencies=[RequireScope("admin")],
)
async def create_knowledge_doc(payload: KnowledgeDocCreate, store: StoreD):
    """Create or update a knowledge doc (admin only). Upserts by unique key."""
    try:
        return await store.upsert_knowledge_doc(payload, user_id=store.user_id)
    except (KnowledgeSizeExceeded, KnowledgeOrgQuotaExceeded, KnowledgeDuplicate) as exc:
        raise _map_knowledge_exc(exc) from exc


@router.put(
    "/knowledge/{doc_id}",
    response_model=KnowledgeDoc,
    dependencies=[RequireScope("admin")],
)
async def update_knowledge_doc(doc_id: str, body_update: KnowledgeDocUpdate, store: StoreD):
    """Update the body of a knowledge doc (admin only). Appends edit history."""
    try:
        return await store.update_knowledge_body(doc_id, body=body_update.body, user_id=store.user_id)
    except (KnowledgeSizeExceeded, KnowledgeOrgQuotaExceeded, KnowledgeNotFound) as exc:
        raise _map_knowledge_exc(exc) from exc


@router.delete("/knowledge/{doc_id}", status_code=204, dependencies=[RequireScope("admin")])
async def archive_knowledge_doc(doc_id: str, store: StoreD):
    """Archive a knowledge doc (admin only)."""
    archived = await store.archive_knowledge_doc(doc_id)
    if not archived:
        raise HTTPException(status_code=404, detail=f"Knowledge doc '{doc_id}' not found")


@router.post(
    "/knowledge/{doc_id}/approve",
    response_model=KnowledgeDoc,
    dependencies=[RequireScope("admin")],
)
async def approve_knowledge_doc(doc_id: str, store: StoreD):
    """Approve a pending knowledge doc (admin only). Flips status from pending to active."""
    try:
        return await store.approve_knowledge_doc(doc_id, user_id=store.user_id)
    except (KnowledgeNotFound, KnowledgeStateConflict) as exc:
        raise _map_knowledge_exc(exc) from exc


@router.get(
    "/knowledge/{doc_id}/edits",
    response_model=list[KnowledgeEdit],
    dependencies=[RequireScope("read")],
)
async def list_knowledge_edits(doc_id: str, store: StoreD, limit: int = 20):
    """Get the edit history for a knowledge doc."""
    return await store.list_knowledge_edits(doc_id, limit=max(1, min(limit, 100)))
