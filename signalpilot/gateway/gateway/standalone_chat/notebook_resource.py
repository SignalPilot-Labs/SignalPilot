"""Conversation notebook resource.

A chat conversation owns one or more named notebooks. "analysis" is the
default notebook every conversation starts with. This module answers one
question for the UI in a single call: where is each notebook now, and what
is its saved content?

The answer has two parts per notebook:
- Attach ids for the live kernel, taken from the conversation's notebook
  rows (or, for legacy conversations, the pointer columns on the
  conversation row). The chat worker writes both on each notebook start.
- The newest archived document (source plus outputs snapshot) for
  kernel-free rendering when the kernel is gone.

Liveness is reconciled here, not trusted. The notebook session row can say
"running" after the sandbox died on its own timeout, because the keepalive
design never stops the session at run end. A short health probe decides,
and a dead session is marked stopped so later reads are cheap and the
notebook proxy fails fast.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import suppress
from typing import Literal

import httpx
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayChatConversation, GatewayChatRuntimeArchive
from gateway.notebooks.session_service import upstream_base_for
from gateway.standalone_chat.object_storage import chat_object_storage
from gateway.store import notebook_sessions as ns
from gateway.store.standalone_chat.notebooks import (
    DEFAULT_NOTEBOOK_NAME,
    list_conversation_notebooks,
)

logger = logging.getLogger(__name__)

# Time budget for the sandbox health probe. A healthy sandbox answers in
# well under one second. A dead route must not delay the panel.
_LIVENESS_PROBE_TIMEOUT_SECONDS = 2.5

# Number of newest archives to examine before giving up on a document.
# A run can complete without an archive, and an object can fail its
# integrity check; walk past both.
_MAX_ARCHIVE_CANDIDATES = 5

_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_SESSION_BYTES = 20 * 1024 * 1024


class ConversationNotebookDocument(BaseModel):
    """Archived notebook content: source code plus optional outputs snapshot."""

    source: str
    session: dict | None = None


class ConversationNotebookInfo(BaseModel):
    """Where one conversation notebook is and what content is saved."""

    status: Literal["live", "ended", "none"]
    name: str = DEFAULT_NOTEBOOK_NAME
    gateway_session_id: str | None = None
    kernel_session_id: str | None = None
    notebook_path: str | None = None
    document: ConversationNotebookDocument | None = None


async def get_conversation_notebooks(
    db: AsyncSession,
    *,
    conversation: GatewayChatConversation,
    http_client: httpx.AsyncClient,
) -> list[ConversationNotebookInfo]:
    """Resolve every notebook of an already-authorized conversation.

    Ordered "analysis" first, then by name. When the child table has no
    rows, the legacy pointer columns become a single "analysis" entry so
    every existing conversation keeps working unchanged.
    """
    rows = await list_conversation_notebooks(db, conversation_id=conversation.id)
    if rows:
        entries: list[tuple[str, str | None, str | None, str | None]] = [
            (row.name, row.gateway_session_id, row.kernel_session_id, row.notebook_path)
            for row in rows
        ]
    else:
        entries = [
            (
                DEFAULT_NOTEBOOK_NAME,
                conversation.notebook_session_id,
                conversation.notebook_kernel_session_id,
                conversation.notebook_path,
            )
        ]
    # Notebooks of one conversation share one sandbox, so probe each
    # gateway session at most once.
    liveness: dict[str, bool] = {}
    infos: list[ConversationNotebookInfo] = []
    for name, gateway_session_id, kernel_session_id, notebook_path in entries:
        live = False
        if gateway_session_id:
            if gateway_session_id not in liveness:
                liveness[gateway_session_id] = await _session_is_live(
                    db,
                    http_client,
                    session_id=gateway_session_id,
                    org_id=conversation.org_id,
                )
            live = liveness[gateway_session_id]
        document = await _latest_document(
            db,
            org_id=conversation.org_id,
            user_id=conversation.user_id,
            conversation_id=conversation.id,
            name=name,
        )
        if live:
            status: Literal["live", "ended", "none"] = "live"
        elif gateway_session_id or document is not None:
            status = "ended"
        else:
            status = "none"
        infos.append(
            ConversationNotebookInfo(
                status=status,
                name=name,
                gateway_session_id=gateway_session_id,
                kernel_session_id=kernel_session_id,
                notebook_path=notebook_path,
                document=document,
            )
        )
    return infos


async def get_conversation_notebook(
    db: AsyncSession,
    *,
    conversation: GatewayChatConversation,
    http_client: httpx.AsyncClient,
) -> ConversationNotebookInfo:
    """Resolve the default notebook for the existing single-notebook endpoint."""
    infos = await get_conversation_notebooks(
        db,
        conversation=conversation,
        http_client=http_client,
    )
    for info in infos:
        if info.name == DEFAULT_NOTEBOOK_NAME:
            return info
    return infos[0]


async def _session_is_live(
    db: AsyncSession,
    http_client: httpx.AsyncClient,
    *,
    session_id: str,
    org_id: str,
) -> bool:
    """Probe the notebook sandbox and reconcile the session row.

    Returns True only when the sandbox answers its health endpoint. When the
    row says "running" but the probe fails, mark the row stopped so the
    proxy and later resource reads fail fast instead of dialing a dead host.
    """
    internal = await ns.get_session_internal(db, session_id=session_id, org_id=org_id)
    if internal is None or internal.status != "running" or not internal.upstream_url:
        return False
    headers = (
        {"Authorization": f"Bearer {internal.access_token}"}
        if internal.access_token
        else {}
    )
    try:
        response = await http_client.get(
            f"{upstream_base_for(internal)}/health",
            headers=headers,
            timeout=_LIVENESS_PROBE_TIMEOUT_SECONDS,
        )
        if response.status_code == 200:
            return True
    except httpx.HTTPError:
        pass
    logger.info("Notebook session %s failed its liveness probe; marking stopped", session_id)
    with suppress(Exception):
        await ns.mark_stopped(db, session_id=session_id, org_id=org_id)
    return False


async def _latest_document(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    conversation_id: str,
    name: str = DEFAULT_NOTEBOOK_NAME,
) -> ConversationNotebookDocument | None:
    """Load the newest intact archived document for one named notebook."""
    name_filter = GatewayChatRuntimeArchive.notebook_name == name
    if name == DEFAULT_NOTEBOOK_NAME:
        # Legacy archives predate notebook names; NULL means "analysis".
        name_filter = or_(name_filter, GatewayChatRuntimeArchive.notebook_name.is_(None))
    archives = (
        (
            await db.execute(
                select(GatewayChatRuntimeArchive)
                .where(
                    GatewayChatRuntimeArchive.conversation_id == conversation_id,
                    GatewayChatRuntimeArchive.org_id == org_id,
                    GatewayChatRuntimeArchive.user_id == user_id,
                    name_filter,
                )
                .order_by(GatewayChatRuntimeArchive.created_at.desc())
                .limit(_MAX_ARCHIVE_CANDIDATES)
            )
        )
        .scalars()
        .all()
    )
    storage = chat_object_storage()
    for archive in archives:
        try:
            source = await storage.get_bytes(
                archive.source_object_key, max_bytes=_MAX_SOURCE_BYTES
            )
        except Exception:
            logger.warning("Archive %s source read failed; trying older archive", archive.id)
            continue
        if hashlib.sha256(source).hexdigest() != archive.source_hash:
            logger.warning("Archive %s failed source integrity; trying older archive", archive.id)
            continue
        session_value = None
        if archive.session_object_key and archive.session_hash:
            with suppress(Exception):
                snapshot = await storage.get_bytes(
                    archive.session_object_key, max_bytes=_MAX_SESSION_BYTES
                )
                if hashlib.sha256(snapshot).hexdigest() == archive.session_hash:
                    parsed = json.loads(snapshot)
                    if isinstance(parsed, dict):
                        session_value = parsed
        return ConversationNotebookDocument(
            source=source.decode("utf-8"),
            session=session_value,
        )
    return None
