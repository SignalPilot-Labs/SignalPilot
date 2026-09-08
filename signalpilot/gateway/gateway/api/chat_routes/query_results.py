"""Chat-scoped full-row access to a structured query result.

Backs the "Load all rows" action on a query card in the chat transcript.

This route is deliberately NOT gated by
``enterprise_chat_feature_flags().structured_results``. That flag governs the
agent-facing feature (whether the SDK route hands full result sets back to the
notebook runtime). Here the caller is the conversation owner, who already saw
these rows rendered in their own transcript; paging through the rest of the
same result is a display concern, not a new capability grant. Ownership is
enforced instead: the result must belong to the caller's org, user, and the
conversation named in the path.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from gateway.db.models import GatewayStructuredQueryResult
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.query_results import QueryResultUnavailable, load_result_rows
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD
from .common import owned_conversation_or_404, require_enabled, require_enterprise_feature

router = APIRouter()

DEFAULT_LIMIT = 500
MAX_LIMIT = 1000


def _connection_name(provenance: object) -> str | None:
    if not isinstance(provenance, dict):
        return None
    value = provenance.get("connection_name")
    return value if isinstance(value, str) and value else None


def _clamp(offset: int, limit: int) -> tuple[int, int]:
    """Clamp instead of rejecting: offset >= 0, 1 <= limit <= MAX_LIMIT."""
    return max(0, offset), min(max(1, limit), MAX_LIMIT)


async def _result_page(stored: GatewayStructuredQueryResult, *, offset: int, limit: int) -> dict:
    try:
        rows = await load_result_rows(stored)
    except QueryResultUnavailable as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "result_id": stored.id,
        "execution_id": stored.execution_id,
        "columns": stored.columns_json,
        "rows": rows[offset : offset + limit],
        "offset": offset,
        "limit": limit,
        "saved_row_count": stored.saved_row_count,
        "query_row_count": stored.query_row_count,
        "completeness": stored.result_completeness,
        "truncation_reason": stored.truncation_reason,
        "connection_name": _connection_name(stored.provenance_json),
    }


@router.get(
    "/conversations/{conversation_id}/results/{result_id}",
    dependencies=[RequireScope("read")],
)
async def get_conversation_query_result(
    conversation_id: str,
    result_id: str,
    store: StoreD,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
):
    """Return one page of saved rows for a result the owner produced in this conversation."""
    require_enabled()
    await owned_conversation_or_404(store, conversation_id)
    offset, limit = _clamp(offset, limit)
    stored = (
        await store.session.execute(
            select(GatewayStructuredQueryResult).where(
                GatewayStructuredQueryResult.id == result_id,
                GatewayStructuredQueryResult.org_id == store._require_org_id(),
                GatewayStructuredQueryResult.conversation_id == conversation_id,
                GatewayStructuredQueryResult.owner_user_id == (store.user_id or "local"),
            )
        )
    ).scalar_one_or_none()
    if stored is None:
        raise HTTPException(status_code=404, detail="Query result not found")
    return await _result_page(stored, offset=offset, limit=limit)


@router.get(
    "/shared/{token}/results/{result_id}",
    dependencies=[RequireScope("read")],
)
async def get_shared_query_result(
    token: str,
    result_id: str,
    store: StoreD,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
):
    """Same page shape for a shared chat, scoped to the grant's owner and conversation."""
    require_enabled()
    require_enterprise_feature("organization_sharing")
    offset, limit = _clamp(offset, limit)
    stored = await chat_store.get_shared_query_result(
        store.session,
        org_id=store._require_org_id(),
        token=token,
        result_id=result_id,
    )
    if stored is None:
        raise HTTPException(status_code=404, detail="Query result not found")
    return await _result_page(stored, offset=offset, limit=limit)
