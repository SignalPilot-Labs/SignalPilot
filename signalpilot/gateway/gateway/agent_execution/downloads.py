"""Mint and atomically redeem opaque download capabilities."""

import secrets
import hashlib
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, exists, func, select

from gateway.config.gateway import get_gateway_settings
from gateway.db.models import GatewayArtifactDownload, GatewayChatConversation, GatewayChatFile
from gateway.standalone_chat.config import runtime_env

DOWNLOAD_PATH = "/api/artifact-download"
TTL_SECONDS = 120


def download_endpoint():
    base = get_gateway_settings().sp_public_gateway_url.rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Public gateway URL is invalid")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "gateway"}:
        raise ValueError("Artifact downloads require an HTTPS public gateway URL")
    return base + DOWNLOAD_PATH


async def mint_downloads(db, org_id, user_id, thread_id, prepared):
    endpoint = download_endpoint()
    now = await db.scalar(select(func.clock_timestamp()))
    expires = now + timedelta(seconds=TTL_SECONDS)
    await db.execute(delete(GatewayArtifactDownload).where(GatewayArtifactDownload.expires_at <= func.clock_timestamp()))
    grants = []
    for row, object_key in prepared:
        token = secrets.token_urlsafe(32)
        db.add(GatewayArtifactDownload(
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            org_id=org_id, user_id=user_id, conversation_id=thread_id, artifact_id=row.id,
            runtime_env=runtime_env() or None, object_key=object_key, filename=row.filename,
            byte_size=row.byte_size, content_hash=row.content_hash, expires_at=expires,
        ))
        grants.append({"download_url": endpoint + "#" + token, "expires_at": expires.isoformat()})
    await db.commit()
    return grants


async def redeem_download(db, token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    active_chat = exists().where(
        GatewayChatConversation.id == GatewayArtifactDownload.conversation_id,
        GatewayChatConversation.org_id == GatewayArtifactDownload.org_id,
        GatewayChatConversation.user_id == GatewayArtifactDownload.user_id,
        GatewayChatConversation.status == "active",
    )
    active_file = exists().where(
        GatewayChatFile.id == GatewayArtifactDownload.artifact_id,
        GatewayChatFile.conversation_id == GatewayArtifactDownload.conversation_id,
        GatewayChatFile.org_id == GatewayArtifactDownload.org_id,
        GatewayChatFile.user_id == GatewayArtifactDownload.user_id,
        GatewayChatFile.status == "active",
    )
    grant = (await db.execute(delete(GatewayArtifactDownload).where(
        GatewayArtifactDownload.token_hash == digest,
        GatewayArtifactDownload.expires_at > func.clock_timestamp(),
        GatewayArtifactDownload.runtime_env == (runtime_env() or None),
        active_chat, active_file,
    ).returning(GatewayArtifactDownload))).scalar_one_or_none()
    await db.commit()
    return grant
