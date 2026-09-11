"""Saved chat artifacts shared by MCP discovery and agent results."""

import asyncio
import hashlib

from sqlalchemy import select

from gateway.db.engine import get_session_factory
from gateway.db.models import GatewayChatConversation, GatewayChatRun
from gateway.mcp.context import mcp_allowed_connection_var
from gateway.standalone_chat.config import runtime_env
from gateway.standalone_chat.object_storage import chat_object_storage, conversation_prefix
from gateway.store import Store
from gateway.store.standalone_chat.files import list_conversation_files
from .downloads import download_endpoint, mint_downloads

MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


async def artifact_rows(db, org_id, user_id, run):
    allowed = mcp_allowed_connection_var.get(None)
    if allowed:
        project = await Store(db, org_id=org_id, user_id=user_id).get_workspace_project(run.project_id)
        if project is None or project.connection_name != allowed:
            raise ValueError("Chat is outside this credential's connection scope")
    rows = await list_conversation_files(
        db, org_id=org_id, user_id=user_id, conversation_id=run.conversation_id,
    )
    return rows


def artifact_metadata(row):
    return {
        "artifact_id": row.id, "filename": row.filename, "path": row.path,
        "mime_type": row.mime_type, "kind": row.kind, "byte_size": row.byte_size,
        "sha256": row.content_hash, "origin_run_id": row.origin_run_id,
    }


async def artifact_manifest(db, org_id, user_id, run):
    return [artifact_metadata(row) for row in await artifact_rows(db, org_id, user_id, run)]


async def read_artifacts(org_id, user_id, thread_id, artifact_ids=None):
    if artifact_ids is not None and (not 1 <= len(artifact_ids) <= 20 or len(set(artifact_ids)) != len(artifact_ids)):
        raise ValueError("Provide 1 to 20 distinct artifact IDs")
    async with get_session_factory()() as db:
        conversation = await db.scalar(select(GatewayChatConversation).where(
            GatewayChatConversation.id == thread_id,
            GatewayChatConversation.org_id == org_id,
            GatewayChatConversation.user_id == user_id,
            GatewayChatConversation.status == "active",
        ))
        if conversation is None:
            raise ValueError("Chat not found")
        run = await db.scalar(select(GatewayChatRun).where(
            GatewayChatRun.conversation_id == thread_id,
            GatewayChatRun.org_id == org_id,
            GatewayChatRun.user_id == user_id,
        ).order_by(GatewayChatRun.created_at.desc(), GatewayChatRun.id.desc()).limit(1))
        if run is None or (run.runtime_env or None) != (runtime_env() or None):
            raise ValueError("Chat run not found in this environment")
        rows = await artifact_rows(db, org_id, user_id, run)
        data = {"thread_id": thread_id, "run_id": run.id, "status": run.status,
                "artifact_scope": "current_chat_manifest"}
        if artifact_ids is None:
            return {**data, "artifacts": [artifact_metadata(row) for row in rows]}
        by_id = {row.id: row for row in rows}
        if any(artifact_id not in by_id for artifact_id in artifact_ids):
            raise ValueError("An artifact was not found in this chat's active manifest. Call list_artifacts again.")
        selected = [by_id[artifact_id] for artifact_id in artifact_ids]
        if sum(row.byte_size for row in selected) > MAX_DOWNLOAD_BYTES:
            raise ValueError("Selected artifacts exceed the 100 MiB batch limit")
        prefix = conversation_prefix(org_id, thread_id) + "/"
        if any(not row.object_key.startswith(prefix) for row in selected):
            raise ValueError("Artifact storage scope is invalid")
        download_endpoint()
        storage = chat_object_storage()
        prepared = []
        for row in selected:
            content = await storage.get_bytes(row.object_key, max_bytes=MAX_DOWNLOAD_BYTES)
            digest = await asyncio.to_thread(lambda: hashlib.sha256(content).hexdigest())
            if digest != row.content_hash or len(content) != row.byte_size:
                raise ValueError("Artifact changed during download or failed integrity validation. List artifacts again.")
            key = f"{prefix}exports/{row.id}/{digest}"
            await storage.put_bytes(key=key, data=content, content_type="application/octet-stream")
            prepared.append((row, key))
        metadata = [artifact_metadata(row) for row in selected]
        grants = await mint_downloads(db, org_id, user_id, thread_id, prepared)
        downloads = [{**item, **grant} for item, grant in zip(metadata, grants)]
        return {**data, "artifacts": downloads,
                "instructions": "Single-use links expire in two minutes. In a browser, open the URL and click Download. For agent HTTP tools, split download_url at # and POST to the URL before # with Content-Type: application/json and body {\"token\": \"<fragment after #>\"}; save the response bytes. A GET only returns the download page. Do not log tokens. Failed or interrupted downloads consume the token; request a new link through download_artifacts. No storage URL is exposed."}
