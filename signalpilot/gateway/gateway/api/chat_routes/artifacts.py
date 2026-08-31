"""Runtime artifact, notebook archive, and download routes."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import uuid
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatRun,
    GatewayChatRuntimeArchive,
    GatewayStructuredQueryResult,
)
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.artifacts import table_to_csv
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.object_storage import chat_object_storage, runtime_object_key
from gateway.store import standalone_chat as chat_store

from ..deps import StoreD
from .common import require_enabled as _require_enabled
from .common import require_enterprise_feature as _require_enterprise_feature

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


async def _runtime_result_rows(result: GatewayStructuredQueryResult) -> list[dict]:
    if result.storage_kind != "object":
        return list(result.rows_json or [])
    if not result.object_key:
        raise HTTPException(status_code=422, detail="Artifact result payload is unavailable")
    data = await chat_object_storage().get_bytes(result.object_key, max_bytes=10 * 1024 * 1024)
    if result.content_hash and hashlib.sha256(data).hexdigest() != result.content_hash:
        raise HTTPException(status_code=500, detail="Artifact result failed integrity validation")
    try:
        rows = json.loads(data)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Artifact result payload is invalid") from exc
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise HTTPException(status_code=500, detail="Artifact result payload is invalid")
    return rows


class RuntimeArtifactCreate(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    kind: str = Field(..., pattern=r"^(table|chart|report)$")
    result_id: str = Field(..., min_length=1, max_length=200)
    content_base64: str = Field(..., min_length=1, max_length=14 * 1024 * 1024)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    exclusions: list[str] = Field(default_factory=list, max_length=100)
    caveats: list[str] = Field(default_factory=list, max_length=100)
    code_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")


class RuntimeArchiveCreate(BaseModel):
    source_base64: str = Field(..., min_length=1, max_length=3 * 1024 * 1024)
    html_base64: str = Field(..., min_length=1, max_length=14 * 1024 * 1024)
    manifest_base64: str = Field(..., min_length=1, max_length=3 * 1024 * 1024)
    # Structured outputs snapshot (NotebookSessionV1) — optional; enables
    # kernel-free rehydration of the real notebook view.
    session_base64: str | None = Field(
        default=None, min_length=1, max_length=27 * 1024 * 1024
    )


@router.post("/runtime-artifacts", status_code=201, dependencies=[RequireScope("query")])
async def publish_runtime_artifact(body: RuntimeArtifactCreate, store: StoreD, request: Request):
    if not enterprise_chat_feature_flags().runtime_artifacts:
        raise HTTPException(status_code=404, detail="Runtime artifact publication is not enabled")
    claims = getattr(request.state, "_jwt_claims", {}) or {}
    identity = claims.get("execution_identity")
    if not isinstance(identity, str) or not identity.startswith("chat:"):
        raise HTTPException(status_code=403, detail="Runtime artifact publication requires a chat run")
    run_id = identity.removeprefix("chat:")
    run = (
        await store.session.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.org_id == store._require_org_id(),
                GatewayChatRun.user_id == (store.user_id or "local"),
                GatewayChatRun.project_id == claims.get("project_id"),
                GatewayChatRun.status == "running",
                GatewayChatRun.cancellation_requested_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=403, detail="Runtime artifact scope mismatch")
    source_result = (
        await store.session.execute(
            select(GatewayStructuredQueryResult).where(
                GatewayStructuredQueryResult.id == body.result_id,
                GatewayStructuredQueryResult.org_id == run.org_id,
                GatewayStructuredQueryResult.owner_user_id == run.user_id,
                GatewayStructuredQueryResult.conversation_id == run.conversation_id,
                GatewayStructuredQueryResult.run_id == run.id,
            )
        )
    ).scalar_one_or_none()
    if source_result is None:
        raise HTTPException(status_code=422, detail="Artifact result_id must belong to the active run")
    if source_result.code_hash and source_result.code_hash != body.code_hash:
        raise HTTPException(status_code=422, detail="Artifact code hash does not match its derived result")
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Artifact content is not valid base64") from exc
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Artifact must be non-empty and no larger than 10 MiB")

    payload: dict = {
        "kind": body.kind,
        "filename": body.filename,
        "assumptions": body.assumptions,
        "exclusions": body.exclusions,
        "caveats": body.caveats,
        "provenance": {
            "result_id": source_result.id,
            "source_result_ids": source_result.source_result_ids_json,
            "code_hash": body.code_hash,
        },
    }
    if body.kind == "table":
        try:
            text_value = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text_value))
            rows = list(reader)
        except (UnicodeDecodeError, csv.Error) as exc:
            raise HTTPException(status_code=422, detail="Table artifact must be valid UTF-8 CSV") from exc
        if not reader.fieldnames or len(rows) > 100_000:
            raise HTTPException(status_code=422, detail="Table artifact must have headers and at most 100,000 rows")
        payload["mime_type"] = "text/csv"
        payload["snapshot"] = {
            "columns": [{"name": name, "type": "string"} for name in reader.fieldnames],
            "rows": rows,
            "saved_row_count": len(rows),
            "completeness": source_result.result_completeness,
            "truncated": source_result.result_completeness != "complete",
        }
    elif body.kind == "chart":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(status_code=422, detail="Chart artifact content does not match PNG")
        source_rows = await _runtime_result_rows(source_result)
        payload["mime_type"] = "image/png"
        payload["binary_base64"] = body.content_base64
        payload["snapshot"] = {
            "runtime_png": True,
            "spec": {},
            "rows": list(source_result.preview_rows_json or []),
            "source": {
                "columns": source_result.columns_json,
                "rows": source_rows,
                "saved_row_count": source_result.saved_row_count,
                "truncated": source_result.result_completeness != "complete",
            },
            "truncated": source_result.result_completeness != "complete",
        }
    else:
        try:
            html_value = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="Report artifact must be valid UTF-8 HTML") from exc
        payload["mime_type"] = "text/html"
        payload["snapshot"] = {"html": html_value}

    try:
        artifact = await chat_store.persist_artifact(store.session, run=run, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await chat_store.append_event(
        store.session,
        run_id=run.id,
        event_type="artifact_created",
        payload={"artifact_id": artifact.id, "kind": artifact.kind, "filename": artifact.filename},
    )
    return {
        "artifact_id": artifact.id,
        "filename": artifact.filename,
        "kind": artifact.kind,
        "byte_size": artifact.byte_size or len(content),
    }


@router.post("/runtime-archives", status_code=201, dependencies=[RequireScope("query")])
async def publish_runtime_archive(body: RuntimeArchiveCreate, store: StoreD, request: Request):
    if not enterprise_chat_feature_flags().runtime_artifacts:
        raise HTTPException(status_code=404, detail="Runtime notebook archives are not enabled")
    claims = getattr(request.state, "_jwt_claims", {}) or {}
    identity = claims.get("execution_identity")
    if not isinstance(identity, str) or not identity.startswith("chat:"):
        raise HTTPException(status_code=403, detail="Runtime archive publication requires a chat run")
    run_id = identity.removeprefix("chat:")
    run = (
        await store.session.execute(
            select(GatewayChatRun).where(
                GatewayChatRun.id == run_id,
                GatewayChatRun.org_id == store._require_org_id(),
                GatewayChatRun.user_id == (store.user_id or "local"),
                GatewayChatRun.project_id == claims.get("project_id"),
                GatewayChatRun.status == "running",
                GatewayChatRun.cancellation_requested_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=403, detail="Runtime archive scope mismatch")
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
    existing = (
        await store.session.execute(select(GatewayChatRuntimeArchive).where(GatewayChatRuntimeArchive.run_id == run.id))
    ).scalar_one_or_none()
    if existing is not None:
        if archive_hashes != (existing.source_hash, existing.html_hash, existing.manifest_hash):
            raise HTTPException(status_code=409, detail="Runtime archive is already bound to different content")
        return {"archive_id": existing.id, "run_id": run.id}
    archive_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"signalpilot-runtime-archive:{run.id}"))
    storage = chat_object_storage()
    objects = []
    try:
        for _label, filename, data, content_type in (
            ("source", "analysis.py", source, "text/x-python"),
            ("html", "analysis.html", html, "text/html"),
            ("manifest", "manifest.json", manifest, "application/json"),
            *(
                (("session", "session.json", session_snapshot, "application/json"),)
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
    run.runtime_archive_id = archive.id
    try:
        await store.session.commit()
    except IntegrityError as exc:
        await store.session.rollback()
        winner = (
            await store.session.execute(
                select(GatewayChatRuntimeArchive).where(GatewayChatRuntimeArchive.run_id == run.id)
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


@router.get("/artifacts/{artifact_id}/download", dependencies=[RequireScope("read")])
async def download_artifact(
    artifact_id: str,
    store: StoreD,
    format: Annotated[str, Query(pattern=r"^(csv|png|html)$")],
):
    _require_enabled()
    artifact = await chat_store.get_artifact(
        store.session,
        org_id=store._require_org_id(),
        user_id=store.user_id or "local",
        artifact_id=artifact_id,
    )
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found",
            headers={"Cache-Control": "private, no-store"},
        )
    return await _artifact_download_response(artifact, format)


@router.get(
    "/shared/{token}/artifacts/{artifact_id}/download",
    dependencies=[RequireScope("read")],
)
async def download_shared_artifact(
    token: str,
    artifact_id: str,
    store: StoreD,
    format: Annotated[str, Query(pattern=r"^(csv|png|html)$")],
):
    _require_enabled()
    _require_enterprise_feature("organization_sharing")
    artifact = await chat_store.get_shared_artifact(
        store.session,
        org_id=store._require_org_id(),
        token=token,
        artifact_id=artifact_id,
    )
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found",
            headers={"Cache-Control": "private, no-store"},
        )
    return await _artifact_download_response(artifact, format)


async def _artifact_download_response(
    artifact: GatewayChatArtifact,
    format: str,
) -> Response:
    allowed = {
        "table": {"csv"},
        "chart": {"png", "csv"},
        "report": {"html"},
    }[artifact.kind]
    if format not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported artifact format")
    if format == "csv" and artifact.storage_kind == "object":
        key = artifact.source_object_key if artifact.kind == "chart" else artifact.object_key
        if not key:
            raise HTTPException(status_code=422, detail="Artifact has no downloadable source rows")
        content = await chat_object_storage().get_bytes(key, max_bytes=10 * 1024 * 1024)
        if (
            key == artifact.object_key
            and artifact.content_hash
            and hashlib.sha256(content).hexdigest() != artifact.content_hash
        ):
            raise HTTPException(status_code=500, detail="Artifact failed integrity validation")
        media_type = "text/csv; charset=utf-8"
    elif format == "csv":
        if artifact.kind == "table" and artifact.binary_data:
            content = artifact.binary_data
            media_type = "text/csv; charset=utf-8"
        else:
            snapshot = artifact.snapshot_json.get("source") if artifact.kind == "chart" else artifact.snapshot_json
            if artifact.kind == "chart" and not isinstance(snapshot, dict):
                snapshot = artifact.snapshot_json
            if not isinstance(snapshot, dict):
                raise HTTPException(status_code=422, detail="Artifact has no downloadable source rows")
            content = table_to_csv(snapshot)
            media_type = "text/csv; charset=utf-8"
    elif format == "png":
        if artifact.storage_kind == "object" and artifact.object_key:
            content = await chat_object_storage().get_bytes(
                artifact.object_key,
                max_bytes=10 * 1024 * 1024,
            )
            if artifact.content_hash and hashlib.sha256(content).hexdigest() != artifact.content_hash:
                raise HTTPException(status_code=500, detail="Artifact failed integrity validation")
        elif artifact.binary_data:
            content = artifact.binary_data
        else:
            raise HTTPException(status_code=422, detail="Artifact has no PNG representation")
        media_type = "image/png"
    else:
        if artifact.storage_kind == "object" and artifact.object_key:
            content = await chat_object_storage().get_bytes(
                artifact.object_key,
                max_bytes=10 * 1024 * 1024,
            )
            if artifact.content_hash and hashlib.sha256(content).hexdigest() != artifact.content_hash:
                raise HTTPException(status_code=500, detail="Artifact failed integrity validation")
        else:
            content = str(artifact.snapshot_json.get("html") or "").encode("utf-8")
        media_type = "text/html; charset=utf-8"
    base = artifact.filename.rsplit(".", 1)[0]
    filename = f"{base}.{format}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
