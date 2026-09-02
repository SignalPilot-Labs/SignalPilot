"""Conversation file manifest, file content, and SQL trace routes."""

from __future__ import annotations

import asyncio
import hashlib
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from gateway.db.models import GatewayChatFile
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.object_storage import chat_object_storage
from gateway.standalone_chat.sql_trace import list_sql_trace
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD
from .artifacts import _ARCHIVE_CSP, _sanitize_runtime_archive_html
from .common import owned_conversation_or_404 as _owned_conversation_or_404
from .common import require_enabled as _require_enabled

router = APIRouter()

_MAX_FILE_BYTES = 100 * 1024 * 1024

# Types that execute script when a browser opens them as a document.
_FORCED_DOWNLOAD_MIMES = {
    "image/svg+xml",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
}


def _file_info(row: GatewayChatFile) -> dict:
    return {
        "id": row.id,
        "path": row.path,
        "filename": row.filename,
        "kind": row.kind,
        "mime_type": row.mime_type,
        "byte_size": row.byte_size,
        "content_hash": row.content_hash,
        "origin_run_id": row.origin_run_id,
        "origin": row.origin,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get(
    "/conversations/{conversation_id}/files",
    dependencies=[RequireScope("read")],
)
async def list_conversation_files(conversation_id: str, store: StoreD):
    """Return the conversation's file manifest, newest change first."""
    _require_enabled()
    await _owned_conversation_or_404(store, conversation_id)
    rows = await chat_store.list_conversation_files(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    return {"files": [_file_info(row) for row in rows]}


@router.get(
    "/conversations/{conversation_id}/files/{file_id}/content",
    dependencies=[RequireScope("read")],
)
async def get_conversation_file_content(
    conversation_id: str,
    file_id: str,
    store: StoreD,
    download: int = 0,
):
    """Return hash-verified file bytes. HTML is sanitized and CSP-pinned."""
    _require_enabled()
    await _owned_conversation_or_404(store, conversation_id)
    row = await chat_store.get_conversation_file(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
        file_id=file_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="File not found")
    content = await chat_object_storage().get_bytes(row.object_key, max_bytes=_MAX_FILE_BYTES)
    # Hash off the event loop. Files can reach 100 MB.
    digest = await asyncio.to_thread(lambda: hashlib.sha256(content).hexdigest())
    if digest != row.content_hash:
        raise HTTPException(status_code=500, detail="File failed integrity validation")
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
    if row.kind == "html":
        content = _sanitize_runtime_archive_html(content.decode("utf-8", errors="replace")).encode("utf-8")
        headers["Content-Security-Policy"] = _ARCHIVE_CSP
    # SVG and XML can carry scripts when opened as a document. The viewer
    # renders them through inert img/blob elements, so force a download for
    # any direct fetch of these types.
    if (row.mime_type or "").split(";", 1)[0].strip().lower() in _FORCED_DOWNLOAD_MIMES:
        download = 1
    if download:
        # Keep the header well formed for any filename the agent chose.
        # ASCII fallback plus RFC 5987 encoding for everything else.
        ascii_name = re.sub(r'[^\x20-\x7e]|["\\\\]', "_", row.filename) or "file"
        encoded_name = quote(row.filename, safe="")
        headers["Content-Disposition"] = (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'
        )
    return Response(
        content=content,
        media_type=row.mime_type or "application/octet-stream",
        headers=headers,
    )


@router.get(
    "/conversations/{conversation_id}/sql-trace",
    dependencies=[RequireScope("read")],
)
async def get_conversation_sql_trace(conversation_id: str, store: StoreD):
    """Return the conversation's governed query executions in creation order."""
    _require_enabled()
    await _owned_conversation_or_404(store, conversation_id)
    executions = await list_sql_trace(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        conversation_id=conversation_id,
    )
    return {"executions": executions}
