"""Read-only download of legacy published chat artifacts.

The chat agent no longer publishes artifacts. The saved-reports library still
reads the rows the old publish tools created, and its chart and table previews
fetch them through this route. Keep it until the library moves to files.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from gateway.db.models import GatewayChatArtifact, GatewayChatConversation
from gateway.security.scope_guard import RequireScope
from gateway.standalone_chat.artifacts import table_to_csv
from gateway.standalone_chat.object_storage import chat_object_storage

from ..deps import StoreD
from .common import require_enabled as _require_enabled

router = APIRouter()

_MAX_BYTES = 10 * 1024 * 1024
_ALLOWED_FORMATS = {
    "table": {"csv"},
    "chart": {"png", "csv"},
    "report": {"html"},
}


async def _owned_artifact(store: StoreD, artifact_id: str) -> GatewayChatArtifact | None:
    return (
        await store.session.execute(
            select(GatewayChatArtifact)
            .join(
                GatewayChatConversation,
                GatewayChatConversation.id == GatewayChatArtifact.conversation_id,
            )
            .where(
                GatewayChatArtifact.id == artifact_id,
                GatewayChatArtifact.org_id == store._require_org_id(),
                GatewayChatArtifact.user_id == (store.user_id or "local"),
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).scalar_one_or_none()


async def _object_bytes(artifact: GatewayChatArtifact, key: str, *, verify: bool) -> bytes:
    content = await chat_object_storage().get_bytes(key, max_bytes=_MAX_BYTES)
    if verify and artifact.content_hash and hashlib.sha256(content).hexdigest() != artifact.content_hash:
        raise HTTPException(status_code=500, detail="Artifact failed integrity validation")
    return content


async def _csv_bytes(artifact: GatewayChatArtifact) -> bytes:
    if artifact.storage_kind == "object":
        key = artifact.source_object_key if artifact.kind == "chart" else artifact.object_key
        if not key:
            raise HTTPException(status_code=422, detail="Artifact has no downloadable source rows")
        return await _object_bytes(artifact, key, verify=key == artifact.object_key)
    if artifact.kind == "table" and artifact.binary_data:
        return artifact.binary_data
    snapshot = artifact.snapshot_json or {}
    if artifact.kind == "chart" and isinstance(snapshot.get("source"), dict):
        snapshot = snapshot["source"]
    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=422, detail="Artifact has no downloadable source rows")
    return table_to_csv(snapshot)


async def _png_bytes(artifact: GatewayChatArtifact) -> bytes:
    if artifact.storage_kind == "object" and artifact.object_key:
        return await _object_bytes(artifact, artifact.object_key, verify=True)
    if artifact.binary_data:
        return artifact.binary_data
    raise HTTPException(status_code=422, detail="Artifact has no PNG representation")


async def _html_bytes(artifact: GatewayChatArtifact) -> bytes:
    if artifact.storage_kind == "object" and artifact.object_key:
        return await _object_bytes(artifact, artifact.object_key, verify=True)
    return str((artifact.snapshot_json or {}).get("html") or "").encode("utf-8")


@router.get("/artifacts/{artifact_id}/download", dependencies=[RequireScope("read")])
async def download_legacy_artifact(
    artifact_id: str,
    store: StoreD,
    format: Annotated[str, Query(pattern=r"^(csv|png|html)$")],
):
    """Return the bytes of one legacy published artifact in the asked format."""
    _require_enabled()
    artifact = await _owned_artifact(store, artifact_id)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found",
            headers={"Cache-Control": "private, no-store"},
        )
    if format not in _ALLOWED_FORMATS.get(artifact.kind, set()):
        raise HTTPException(status_code=400, detail="Unsupported artifact format")
    if format == "csv":
        content, media_type = await _csv_bytes(artifact), "text/csv; charset=utf-8"
    elif format == "png":
        content, media_type = await _png_bytes(artifact), "image/png"
    else:
        content, media_type = await _html_bytes(artifact), "text/html; charset=utf-8"
    base = artifact.filename.rsplit(".", 1)[0]
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{base}.{format}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
