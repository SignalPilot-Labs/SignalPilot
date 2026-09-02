"""Runtime file ingest: the sandbox pushes scratch files to the gateway.

The sandbox sweeps its scratch directory at every tool boundary and posts
each new or changed file here with the run's scoped token. The route
validates the path, verifies the hash, refuses token-bearing bytes, stores
the object, upserts the manifest row, and appends one files_changed event.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from gateway.db.models import GatewayChatFile, GatewayChatRun
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.config import (
    chat_file_max_bytes,
    conversation_file_quota_bytes,
    conversation_file_quota_count,
)
from gateway.standalone_chat.object_storage import chat_object_storage, conversation_file_key
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD
from .common import require_enabled as _require_enabled
from .common import running_run_for_execution_identity as _running_run_for_execution_identity

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_PATH_CHARS = 512
_SKIPPED_SEGMENTS = {"__pycache__"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f\"\\]")
_PATH_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_SVG_SCAN_BYTES = 4096

# Magic-byte prefixes for the image kinds the transcript can show inline.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_MIME_BY_EXTENSION = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".jsonl": "application/x-ndjson",
    ".parquet": "application/vnd.apache.parquet",
    ".sql": "text/x-sql",
    ".py": "text/x-python",
    ".ipynb": "application/x-ipynb+json",
    ".yml": "text/yaml",
    ".yaml": "text/yaml",
    ".toml": "text/plain",
}


def validate_runtime_path(path: str) -> str:
    """Return the path when it is a safe scratch-relative posix path. Raise 422."""
    if not isinstance(path, str) or not path or len(path) > _MAX_PATH_CHARS:
        raise HTTPException(status_code=422, detail="File path must be 1 to 512 characters")
    if path.startswith("/") or "\\" in path or _PATH_CONTROL_CHARS.search(path):
        raise HTTPException(status_code=422, detail="File path must be a relative posix path")
    segments = path.split("/")
    for segment in segments:
        if not segment or segment.startswith("."):
            raise HTTPException(status_code=422, detail="File path has an empty or hidden segment")
        if segment in _SKIPPED_SEGMENTS:
            raise HTTPException(status_code=422, detail="File path is not capturable")
    if len(segments) == 1 and segments[0].lower().endswith(".py"):
        raise HTTPException(
            status_code=422,
            detail="Top-level notebook sources belong to the notebook archive",
        )
    return path


def _display_filename(basename: str) -> str:
    cleaned = _CONTROL_CHARS.sub("_", basename).strip()
    return cleaned[:255] or "file"


def sniff_image_mime(data: bytes) -> str | None:
    """Return the image MIME type proven by the bytes, or None."""
    for signature, mime in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if b"<svg" in data[:_SVG_SCAN_BYTES].lower():
        return "image/svg+xml"
    return None


def classify(filename: str, data: bytes) -> tuple[str, str]:
    """Return (kind, mime_type). Image kinds are verified by magic bytes."""
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    guessed = _MIME_BY_EXTENSION.get(extension) or mimetypes.guess_type(filename)[0]
    kind = chat_store.derive_file_kind(filename, guessed)
    if kind == "image":
        sniffed = sniff_image_mime(data)
        if sniffed is None:
            return "other", "application/octet-stream"
        return "image", sniffed
    return kind, guessed or "application/octet-stream"


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None


def _file_descriptor(row: GatewayChatFile, *, deleted: bool) -> dict:
    return {
        "file_id": row.id,
        "path": row.path,
        "filename": row.filename,
        "kind": row.kind,
        "byte_size": row.byte_size,
        "content_hash": row.content_hash,
        "deleted": deleted,
    }


async def _append_files_changed(
    store: StoreD,
    *,
    run: GatewayChatRun,
    row: GatewayChatFile,
    deleted: bool,
    tool_call_id: str | None,
) -> None:
    await chat_store.append_event(
        store.session,
        run_id=run.id,
        event_type="files_changed",
        payload={
            "changed": 1,
            "files": [_file_descriptor(row, deleted=deleted)],
            "tool_call_id": tool_call_id,
            "origin": "runtime",
        },
    )


async def _soft_delete(
    store: StoreD,
    *,
    run: GatewayChatRun,
    path: str,
    tool_call_id: str | None,
) -> JSONResponse:
    existing = await chat_store.get_conversation_file_by_path(
        store.session,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        path=path,
    )
    if existing is None or existing.status != "active":
        return JSONResponse(
            status_code=200,
            content={"file_id": existing.id if existing else None, "unchanged": True},
        )
    await chat_store.mark_conversation_file_deleted(
        store.session,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        path=path,
    )
    await _append_files_changed(store, run=run, row=existing, deleted=True, tool_call_id=tool_call_id)
    return JSONResponse(status_code=200, content={"file_id": existing.id, "path": path, "deleted": True})


async def _read_bounded(upload: UploadFile, *, max_bytes: int) -> bytes:
    """Read the upload with a hard cap. Raise 413 when the cap is passed."""
    data = await upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="File exceeds the runtime file size limit")
    return data


async def _enforce_quota(
    store: StoreD,
    *,
    run: GatewayChatRun,
    existing: GatewayChatFile | None,
    byte_size: int,
) -> None:
    count, total = await chat_store.conversation_file_usage(
        store.session,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
    )
    replacing = existing is not None and existing.status == "active"
    if replacing:
        count -= 1
        total -= int(existing.byte_size or 0)
    if count + 1 > conversation_file_quota_count():
        raise HTTPException(status_code=413, detail="Conversation file count quota exceeded")
    if total + byte_size > conversation_file_quota_bytes():
        raise HTTPException(status_code=413, detail="Conversation file storage quota exceeded")


@router.post("/runtime-files", status_code=201, dependencies=[RequireScope("query")])
async def publish_runtime_file(
    request: Request,
    store: StoreD,
    path: Annotated[str, Form()],
    content_hash: Annotated[str | None, Form()] = None,
    tool_call_id: Annotated[str | None, Form()] = None,
    reason: Annotated[str | None, Form()] = None,
    deleted: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    """Accept one scratch file from the running sandbox."""
    _require_enabled()
    run = await _running_run_for_execution_identity(store, request)
    path = validate_runtime_path(path)
    tool_call_id = (tool_call_id or "").strip()[:200] or None
    if (deleted or "").strip() == "1":
        return await _soft_delete(store, run=run, path=path, tool_call_id=tool_call_id)
    if file is None:
        raise HTTPException(status_code=422, detail="File part is required")
    data = await _read_bounded(file, max_bytes=chat_file_max_bytes())
    digest = await asyncio.to_thread(lambda: hashlib.sha256(data).hexdigest())
    if not content_hash or content_hash.strip().lower() != digest:
        raise HTTPException(status_code=422, detail="content_hash does not match the uploaded bytes")
    token = _bearer_token(request)
    if token and token.encode("utf-8") in data:
        raise HTTPException(status_code=422, detail="File content was rejected")

    filename = _display_filename(path.rsplit("/", 1)[-1])
    kind, mime_type = classify(filename, data)
    existing = await chat_store.get_conversation_file_by_path(
        store.session,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        path=path,
    )
    if existing is not None and existing.status == "active" and existing.content_hash == digest:
        logger.info("runtime file unchanged run=%s path=%s reason=%s", run.id, path, reason)
        return JSONResponse(status_code=200, content={"file_id": existing.id, "unchanged": True})
    await _enforce_quota(store, run=run, existing=existing, byte_size=len(data))

    file_id = existing.id if existing is not None else str(uuid.uuid4())
    object_key = existing.object_key if existing is not None else conversation_file_key(
        org_id=run.org_id,
        conversation_id=run.conversation_id,
        file_id=file_id,
        filename=filename,
    )
    await chat_object_storage().put_bytes(key=object_key, data=data, content_type=mime_type)
    row = await chat_store.upsert_conversation_file(
        store.session,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        path=path,
        filename=filename,
        mime_type=mime_type,
        byte_size=len(data),
        content_hash=digest,
        object_key=object_key,
        origin_run_id=run.id,
        origin="runtime",
        kind=kind,
        file_id=file_id,
    )
    await _append_files_changed(store, run=run, row=row, deleted=False, tool_call_id=tool_call_id)
    logger.info(
        "runtime file stored run=%s path=%s kind=%s bytes=%d reason=%s",
        run.id,
        path,
        row.kind,
        row.byte_size,
        reason,
    )
    return {
        "file_id": row.id,
        "path": row.path,
        "kind": row.kind,
        "byte_size": row.byte_size,
        "content_hash": row.content_hash,
    }
