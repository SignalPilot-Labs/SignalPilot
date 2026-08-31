"""Artifact persistence and retrieval."""

from __future__ import annotations

import base64
import hashlib
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.connectors.schema_cache import _schema_fingerprint, schema_cache
from gateway.db.models import (
    GatewayChatArtifact,
    GatewayChatConversation,
    GatewayChatRun,
    GatewayWorkspaceProject,
)
from gateway.standalone_chat.artifacts import (
    normalize_table_snapshot,
    safe_filename,
    sanitize_chart_snapshot,
    sanitize_report_html,
    table_to_csv,
    validate_artifact_size,
)
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.standalone_chat.domain import redact_public_payload
from gateway.standalone_chat.object_storage import runtime_object_key
from gateway.store.standalone_chat.helpers import _bounded_artifact_notes


def _object_storage():
    """Resolve the storage factory through the package namespace at call time.

    Tests patch chat_object_storage on the package module. Read the name late
    so the patch takes effect."""
    from gateway.store import standalone_chat as chat_store

    return chat_store.chat_object_storage()

async def persist_artifact(
    db: AsyncSession,
    *,
    run: GatewayChatRun,
    payload: dict[str, Any],
) -> GatewayChatArtifact:
    kind = str(payload.get("kind") or "")
    if kind not in {"table", "chart", "report"}:
        raise ValueError("Unsupported artifact kind")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("Artifact snapshot must be an object")
    full_snapshot = snapshot
    binary_data: bytes | None = None
    encoded = payload.get("binary_base64")
    if encoded:
        if len(str(encoded)) > (14 * 1024 * 1024):
            raise ValueError("Artifact exceeds the 10 MiB limit")
        try:
            binary_data = base64.b64decode(str(encoded), validate=True)
        except Exception as exc:
            raise ValueError("Artifact binary is not valid base64") from exc
    if kind == "report":
        html_value = str(snapshot.get("html") or "")
        snapshot = {**snapshot, "html": sanitize_report_html(html_value)}
    elif kind == "chart":
        if binary_data is None:
            raise ValueError("Chart artifacts require a PNG representation")
        snapshot = sanitize_chart_snapshot(snapshot)
    else:
        snapshot = normalize_table_snapshot(snapshot)
    provenance = redact_public_payload(payload.get("provenance") or {})
    # Lineage used by saved-report preflight is server-owned. The agent may
    # supply other public provenance, but it cannot choose the frozen dbt
    # commit or the schema fingerprint observed during this conversation.
    conversation = await db.get(GatewayChatConversation, run.conversation_id)
    if conversation is not None:
        provenance["commit_sha"] = conversation.commit_sha
    project = await db.get(GatewayWorkspaceProject, run.project_id)
    if project is not None and project.connection_name:
        try:
            observed_schema = schema_cache.get(project.connection_name)
        except Exception:
            observed_schema = None
        provenance["schema_fingerprint"] = _schema_fingerprint(observed_schema) if observed_schema is not None else None
    assumptions = _bounded_artifact_notes(payload.get("assumptions"))
    exclusions = _bounded_artifact_notes(payload.get("exclusions"))
    caveats = _bounded_artifact_notes(payload.get("caveats"))
    validate_artifact_size(
        {
            "snapshot": snapshot,
            "provenance": provenance,
            "assumptions": assumptions,
            "exclusions": exclusions,
            "caveats": caveats,
        },
        binary_data,
    )
    default_ext = {"table": ".csv", "chart": ".png", "report": ".html"}[kind]
    filename = safe_filename(str(payload.get("filename") or ""), fallback=f"analysis{default_ext}")
    if not filename.lower().endswith(default_ext):
        filename = f"{filename.rsplit('.', 1)[0]}{default_ext}"
    expected_mime_type = {
        "table": "text/csv",
        "chart": "image/png",
        "report": "text/html",
    }[kind]
    supplied_mime_type = str(payload.get("mime_type") or expected_mime_type).split(";", 1)[0].strip().lower()
    if supplied_mime_type != expected_mime_type:
        raise ValueError("Artifact MIME type does not match its kind")
    mime_type = expected_mime_type
    object_bytes = (
        table_to_csv(full_snapshot)
        if kind == "table"
        else binary_data
        if kind == "chart"
        else str(snapshot.get("html") or "").encode("utf-8")
    )
    assert object_bytes is not None
    if len(object_bytes) > 10 * 1024 * 1024:
        raise ValueError("Artifact exceeds the 10 MiB limit")
    chart_source_bytes: bytes | None = None
    if kind == "chart":
        source = full_snapshot.get("source") if isinstance(full_snapshot.get("source"), dict) else full_snapshot
        chart_source_bytes = table_to_csv(source)
        if len(chart_source_bytes) > 10 * 1024 * 1024:
            raise ValueError("Artifact source exceeds the 10 MiB limit")
    candidate_hash = hashlib.sha256(object_bytes).hexdigest()
    existing = (
        await db.execute(
            select(GatewayChatArtifact).where(
                GatewayChatArtifact.run_id == run.id,
                GatewayChatArtifact.kind == kind,
                GatewayChatArtifact.filename == filename,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # The publication key is idempotent and immutable. A retry cannot
        # replace the first snapshot, even if a caller reconstructs different
        # bytes for the same run/kind/filename tuple.
        return existing
    artifact_id = str(uuid.uuid4())
    storage_kind = "inline"
    object_key = None
    source_object_key = None
    byte_size = len(object_bytes)
    # Content identity is always the SHA-256 of the exact primary downloadable
    # bytes, independently of whether those bytes are inline or object-backed.
    content_hash = candidate_hash
    uploaded_keys: list[str] = []
    if enterprise_chat_feature_flags().runtime_artifacts:
        storage = _object_storage()
        object_key = runtime_object_key(
            org_id=run.org_id,
            conversation_id=run.conversation_id,
            run_id=run.id,
            category="artifacts",
            object_id=artifact_id,
            filename=filename,
        )
        try:
            stored = await storage.put_bytes(key=object_key, data=object_bytes, content_type=mime_type)
            uploaded_keys.append(object_key)
            storage_kind = "object"
            byte_size = stored.byte_size
            content_hash = stored.content_hash
            if kind == "chart":
                assert chart_source_bytes is not None
                source_object_key = runtime_object_key(
                    org_id=run.org_id,
                    conversation_id=run.conversation_id,
                    run_id=run.id,
                    category="artifact-sources",
                    object_id=artifact_id,
                    filename=f"{filename.rsplit('.', 1)[0]}.csv",
                )
                await storage.put_bytes(
                    key=source_object_key,
                    data=chart_source_bytes,
                    content_type="text/csv",
                )
                uploaded_keys.append(source_object_key)
        except Exception:
            for uploaded_key in reversed(uploaded_keys):
                with suppress(Exception):
                    await storage.delete(uploaded_key)
            raise
        binary_data = None
    elif kind == "table":
        # Keep the exact governed CSV bytes alongside the bounded UI snapshot.
        # This makes inline and object-backed content identity identical.
        binary_data = object_bytes
    artifact = GatewayChatArtifact(
        id=artifact_id,
        org_id=run.org_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        kind=kind,
        filename=filename,
        mime_type=mime_type,
        snapshot_json=snapshot,
        binary_data=binary_data,
        storage_kind=storage_kind,
        object_key=object_key,
        source_object_key=source_object_key,
        byte_size=byte_size,
        content_hash=content_hash,
        provenance_json=provenance,
        freshness_at=_parse_datetime(payload.get("freshness_at")),
        assumptions=assumptions,
        exclusions=exclusions,
        caveats=caveats,
        parent_artifact_id=str(payload.get("parent_artifact_id") or "") or None,
    )
    if artifact.parent_artifact_id:
        parent = (
            await db.execute(
                select(GatewayChatArtifact.id).where(
                    GatewayChatArtifact.id == artifact.parent_artifact_id,
                    GatewayChatArtifact.org_id == run.org_id,
                    GatewayChatArtifact.user_id == run.user_id,
                    GatewayChatArtifact.conversation_id == run.conversation_id,
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise ValueError("Parent artifact not found")
    db.add(artifact)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        if uploaded_keys:
            storage = _object_storage()
            for uploaded_key in reversed(uploaded_keys):
                with suppress(Exception):
                    await storage.delete(uploaded_key)
        raise
    await db.refresh(artifact)
    return artifact


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


async def get_artifact(
    db: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    artifact_id: str,
) -> GatewayChatArtifact | None:
    return (
        await db.execute(
            select(GatewayChatArtifact)
            .join(
                GatewayChatConversation,
                GatewayChatConversation.id == GatewayChatArtifact.conversation_id,
            )
            .where(
                GatewayChatArtifact.id == artifact_id,
                GatewayChatArtifact.org_id == org_id,
                GatewayChatArtifact.user_id == user_id,
                GatewayChatConversation.surface == "standalone",
                GatewayChatConversation.status == "active",
            )
        )
    ).scalar_one_or_none()
