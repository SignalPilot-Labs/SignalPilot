"""Runtime notebook archive routes."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from contextlib import suppress

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from gateway.db.models import GatewayChatRun, GatewayChatRuntimeArchive
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.object_storage import chat_object_storage, runtime_object_key
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD
from .common import running_run_for_execution_identity as _running_run_for_execution_identity

router = APIRouter()

_ARCHIVE_CSP = (
    "default-src 'none'; img-src data: blob:; media-src data: blob:; "
    "style-src 'unsafe-inline'; font-src data:; "
    "script-src 'unsafe-inline' 'unsafe-eval' blob:; worker-src blob:; "
    "connect-src 'none'; frame-src 'none'; object-src 'none'; "
    "form-action 'none'; base-uri 'none'"
)


def _sanitize_runtime_archive_html(value: str) -> str:
    """Preserve the static notebook bundle while removing navigation escapes."""
    sanitized = re.sub(
        r"<meta\b[^>]*http-equiv\s*=\s*(['\"]?)refresh\1[^>]*>",
        "",
        value,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"<base\b[^>]*>", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(
        r"<meta\b[^>]*http-equiv\s*=\s*(['\"]?)content-security-policy\1[^>]*>",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    csp_meta = f'<meta http-equiv="Content-Security-Policy" content="{_ARCHIVE_CSP}">'
    with_csp, replacements = re.subn(
        r"<head(\s[^>]*)?>",
        lambda match: f"{match.group(0)}{csp_meta}",
        sanitized,
        count=1,
        flags=re.IGNORECASE,
    )
    if replacements:
        return with_csp
    return re.sub(
        r"<html(\s[^>]*)?>",
        lambda match: f"{match.group(0)}<head>{csp_meta}</head>",
        sanitized,
        count=1,
        flags=re.IGNORECASE,
    )


class RuntimeArchiveCreate(BaseModel):
    source_base64: str = Field(..., min_length=1, max_length=3 * 1024 * 1024)
    html_base64: str = Field(..., min_length=1, max_length=14 * 1024 * 1024)
    manifest_base64: str = Field(..., min_length=1, max_length=3 * 1024 * 1024)
    # Structured outputs snapshot (NotebookSessionV1) — optional; enables
    # kernel-free rehydration of the real notebook view.
    session_base64: str | None = Field(
        default=None, min_length=1, max_length=27 * 1024 * 1024
    )
    # Notebook this archive snapshots. "analysis" is the default notebook.
    notebook_name: str = Field(default="analysis", pattern=r"^[a-z][a-z0-9_-]{0,40}$")


@router.post("/runtime-archives", status_code=201, dependencies=[RequireScope("query")])
async def publish_runtime_archive(body: RuntimeArchiveCreate, store: StoreD, request: Request):
    if not enterprise_chat_feature_flags().runtime_artifacts:
        raise HTTPException(status_code=404, detail="Runtime notebook archives are not enabled")
    run = await _running_run_for_execution_identity(store, request)
    try:
        source = base64.b64decode(body.source_base64, validate=True)
        html = base64.b64decode(body.html_base64, validate=True)
        manifest = base64.b64decode(body.manifest_base64, validate=True)
        session_snapshot = (
            base64.b64decode(body.session_base64, validate=True)
            if body.session_base64
            else None
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Runtime archive payload is not valid base64") from exc
    if len(source) > 2 * 1024 * 1024 or len(html) > 10 * 1024 * 1024 or len(manifest) > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Runtime archive payload exceeds its bounded size")
    if session_snapshot is not None and len(session_snapshot) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Runtime archive payload exceeds its bounded size")
    try:
        source.decode("utf-8")
        html_text = html.decode("utf-8")
        manifest_value = json.loads(manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Runtime archive payload is invalid") from exc
    if not isinstance(manifest_value, dict) or "<html" not in html_text[:10_000].lower():
        raise HTTPException(status_code=422, detail="Runtime archive payload is invalid")
    if session_snapshot is not None:
        # NotebookSessionV1 shape check; a bad snapshot degrades to no
        # outputs rather than rejecting the whole archive.
        try:
            session_value = json.loads(session_snapshot)
            if not isinstance(session_value, dict) or not {
                "version",
                "metadata",
                "cells",
            }.issubset(session_value.keys()):
                session_snapshot = None
        except (UnicodeDecodeError, json.JSONDecodeError):
            session_snapshot = None
    html_text = _sanitize_runtime_archive_html(html_text)
    html = html_text.encode("utf-8")
    archive_hashes = tuple(hashlib.sha256(value).hexdigest() for value in (source, html, manifest))
    notebook_name = body.notebook_name
    # Legacy rows predate notebook names; NULL means "analysis".
    name_filter = GatewayChatRuntimeArchive.notebook_name == notebook_name
    if notebook_name == "analysis":
        name_filter = or_(name_filter, GatewayChatRuntimeArchive.notebook_name.is_(None))
    existing = (
        await store.session.execute(
            select(GatewayChatRuntimeArchive).where(
                GatewayChatRuntimeArchive.run_id == run.id, name_filter
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if archive_hashes != (existing.source_hash, existing.html_hash, existing.manifest_hash):
            raise HTTPException(status_code=409, detail="Runtime archive is already bound to different content")
        return {"archive_id": existing.id, "run_id": run.id}
    # Keep the legacy seed for "analysis" so re-publishes of existing runs
    # stay idempotent.
    seed = f"signalpilot-runtime-archive:{run.id}"
    if notebook_name != "analysis":
        seed = f"signalpilot-runtime-archive:{run.id}:{notebook_name}"
    archive_id = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
    prefix = "" if notebook_name == "analysis" else f"{notebook_name}-"
    storage = chat_object_storage()
    objects = []
    try:
        for _label, filename, data, content_type in (
            ("source", f"{prefix}analysis.py", source, "text/x-python"),
            ("html", f"{prefix}analysis.html", html, "text/html"),
            ("manifest", f"{prefix}manifest.json", manifest, "application/json"),
            *(
                (("session", f"{prefix}session.json", session_snapshot, "application/json"),)
                if session_snapshot is not None
                else ()
            ),
        ):
            key = runtime_object_key(
                org_id=run.org_id,
                conversation_id=run.conversation_id,
                run_id=run.id,
                category="notebook-archive",
                object_id=archive_id,
                filename=filename,
            )
            objects.append(await storage.put_bytes(key=key, data=data, content_type=content_type))
    except Exception:
        for item in reversed(objects):
            with suppress(Exception):
                await storage.delete(item.key)
        raise
    archive = GatewayChatRuntimeArchive(
        id=archive_id,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        notebook_name=notebook_name,
        source_object_key=objects[0].key,
        html_object_key=objects[1].key,
        manifest_object_key=objects[2].key,
        session_object_key=objects[3].key if len(objects) > 3 else None,
        source_hash=objects[0].content_hash,
        html_hash=objects[1].content_hash,
        manifest_hash=objects[2].content_hash,
        session_hash=objects[3].content_hash if len(objects) > 3 else None,
    )
    store.session.add(archive)
    if notebook_name == "analysis":
        run.runtime_archive_id = archive.id
    try:
        await store.session.commit()
    except IntegrityError as exc:
        await store.session.rollback()
        winner = (
            await store.session.execute(
                select(GatewayChatRuntimeArchive).where(
                    GatewayChatRuntimeArchive.run_id == run.id, name_filter
                )
            )
        ).scalar_one_or_none()
        if winner is not None and archive_hashes == (
            winner.source_hash,
            winner.html_hash,
            winner.manifest_hash,
        ):
            return {"archive_id": winner.id, "run_id": run.id}
        for item in reversed(objects):
            with suppress(Exception):
                await storage.delete(item.key)
        raise HTTPException(status_code=409, detail="Runtime archive identity conflict") from exc
    except Exception:
        await store.session.rollback()
        for item in reversed(objects):
            with suppress(Exception):
                await storage.delete(item.key)
        raise
    await chat_store.append_event(
        store.session,
        run_id=run.id,
        event_type="archive_completed",
        payload={"archive_id": archive.id},
    )
    return {"archive_id": archive.id, "run_id": run.id}


@router.get("/runs/{run_id}/notebook", dependencies=[RequireScope("read")])
async def get_runtime_notebook(run_id: str, store: StoreD):
    archive = (
        await store.session.execute(
            select(GatewayChatRuntimeArchive)
            .join(GatewayChatRun, GatewayChatRun.id == GatewayChatRuntimeArchive.run_id)
            .where(
                GatewayChatRuntimeArchive.run_id == run_id,
                GatewayChatRuntimeArchive.org_id == store._require_org_id(),
                GatewayChatRuntimeArchive.user_id == (store.user_id or "local"),
                GatewayChatRun.conversation_id == GatewayChatRuntimeArchive.conversation_id,
            )
        )
    ).scalar_one_or_none()
    if archive is None:
        raise HTTPException(status_code=404, detail="Runtime notebook archive not found")
    content = await chat_object_storage().get_bytes(archive.html_object_key, max_bytes=10 * 1024 * 1024)
    if hashlib.sha256(content).hexdigest() != archive.html_hash:
        raise HTTPException(status_code=500, detail="Runtime notebook archive failed integrity validation")
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": _ARCHIVE_CSP,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
