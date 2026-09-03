"""Connector rows: creation with the slug rule, visibility, updates, secrets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import (
    GatewayMcpConnector,
    GatewayMcpMemberState,
    GatewayMcpOAuthState,
    GatewayMcpToolCall,
)
from gateway.mcp_connectors.slugs import SlugCollisionError, allocate_slug
from gateway.store.mcp._common import decrypt_dict, encrypt_json, utcnow

__all__ = ["ConnectorDraft", "SlugCollisionError"]


@dataclass
class ConnectorDraft:
    scope: str
    name: str
    transport: str
    created_by: str
    owner_user_id: str | None = None
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: list[dict[str, Any]] = field(default_factory=list)
    header_names: list[str] = field(default_factory=list)
    auth: str = "none"
    oauth: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    oauth_client_secret: str | None = None


async def get_connector(session: AsyncSession, *, org_id: str, connector_id: str) -> GatewayMcpConnector | None:
    return (
        await session.execute(
            select(GatewayMcpConnector).where(
                GatewayMcpConnector.org_id == org_id,
                GatewayMcpConnector.id == connector_id,
            )
        )
    ).scalar_one_or_none()


def is_visible_to(connector: GatewayMcpConnector, *, user_id: str, is_admin: bool) -> bool:
    """Org connectors are visible to everyone; personal ones to their owner (admins see all)."""
    if connector.scope == "org":
        return True
    return connector.owner_user_id == user_id or is_admin


async def list_visible(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    is_admin: bool,
) -> list[GatewayMcpConnector]:
    stmt = select(GatewayMcpConnector).where(GatewayMcpConnector.org_id == org_id)
    if not is_admin:
        stmt = stmt.where(
            or_(
                GatewayMcpConnector.scope == "org",
                GatewayMcpConnector.owner_user_id == user_id,
            )
        )
    stmt = stmt.order_by(GatewayMcpConnector.scope, GatewayMcpConnector.name)
    return list((await session.execute(stmt)).scalars())


async def list_effective(session: AsyncSession, *, org_id: str, user_id: str) -> list[GatewayMcpConnector]:
    """Connectors that can be injected for a user: org ones plus their own personal ones."""
    return await list_visible(session, org_id=org_id, user_id=user_id, is_admin=False)


async def _taken_slugs(session: AsyncSession, *, org_id: str, owner_user_id: str | None) -> tuple[set[str], set[str]]:
    rows = list(
        (
            await session.execute(
                select(GatewayMcpConnector.slug, GatewayMcpConnector.owner_user_id).where(
                    GatewayMcpConnector.org_id == org_id
                )
            )
        ).all()
    )
    org_slugs = {slug for slug, owner in rows if owner is None}
    own_slugs = {slug for slug, owner in rows if owner is not None and owner == owner_user_id}
    return org_slugs, own_slugs


async def preview_slug(session: AsyncSession, *, org_id: str, scope: str, owner_user_id: str | None, name: str) -> str:
    """Slug the connector would get on creation (rule R9). Raises SlugCollisionError."""
    org_slugs, own_slugs = await _taken_slugs(session, org_id=org_id, owner_user_id=owner_user_id)
    return allocate_slug(name, scope=scope, org_slugs=org_slugs, own_slugs=own_slugs)


async def create_connector(session: AsyncSession, *, org_id: str, draft: ConnectorDraft) -> GatewayMcpConnector:
    owner = draft.owner_user_id if draft.scope == "personal" else None
    slug = await preview_slug(session, org_id=org_id, scope=draft.scope, owner_user_id=owner, name=draft.name)
    row = GatewayMcpConnector(
        org_id=org_id,
        scope=draft.scope,
        owner_user_id=owner,
        name=draft.name,
        slug=slug,
        transport=draft.transport,
        url=draft.url,
        command=draft.command,
        args_json=list(draft.args),
        env_json=[dict(entry) for entry in draft.env],
        header_names_json=sorted(set(draft.header_names) | set((draft.headers or {}).keys())),
        auth=draft.auth,
        oauth_json=draft.oauth,
        tools_json=[],
        status="pending",
        enabled=True,
        created_by=draft.created_by,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    if draft.headers:
        row.headers_enc = encrypt_json(draft.headers)
    if draft.oauth_client_secret:
        row.oauth_client_secret_enc = encrypt_json({"client_secret": draft.oauth_client_secret})
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_connector(session: AsyncSession, connector: GatewayMcpConnector, **fields: Any) -> GatewayMcpConnector:
    for name, value in fields.items():
        setattr(connector, name, value)
    connector.updated_at = utcnow()
    await session.commit()
    await session.refresh(connector)
    return connector


async def delete_connector(session: AsyncSession, connector: GatewayMcpConnector) -> None:
    """Delete the connector, every member row (tokens, keys) and pending OAuth states."""
    await session.execute(delete(GatewayMcpMemberState).where(GatewayMcpMemberState.connector_id == connector.id))
    await session.execute(delete(GatewayMcpOAuthState).where(GatewayMcpOAuthState.connector_id == connector.id))
    await session.execute(delete(GatewayMcpToolCall).where(GatewayMcpToolCall.connector_id == connector.id))
    await session.delete(connector)
    await session.commit()


def tools_hash(tools: list[dict[str, Any]]) -> str:
    """Hash of the inventory the user approved: names, descriptions and schemas (R11)."""
    canonical = [
        {
            "name": tool.get("name"),
            "description": tool.get("description") or "",
            "input_schema": tool.get("input_schema") or {},
        }
        for tool in sorted(tools, key=lambda item: str(item.get("name")))
    ]
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def static_headers(connector: GatewayMcpConnector) -> dict[str, str]:
    return decrypt_dict(connector, "headers_enc")


def set_static_headers(connector: GatewayMcpConnector, headers: dict[str, str]) -> None:
    connector.headers_enc = encrypt_json(headers) if headers else None
    connector.header_names_json = sorted(set(connector.header_names_json or []) | set(headers.keys()))
    connector.updated_at = utcnow()


def drop_static_header(connector: GatewayMcpConnector, name: str) -> bool:
    current = static_headers(connector)
    removed = current.pop(name, None) is not None
    connector.headers_enc = encrypt_json(current) if current else None
    connector.header_names_json = [n for n in (connector.header_names_json or []) if n != name]
    connector.updated_at = utcnow()
    return removed


def oauth_client_secret(connector: GatewayMcpConnector) -> str | None:
    value = decrypt_dict(connector, "oauth_client_secret_enc")
    return value.get("client_secret") or None


def public_env(connector: GatewayMcpConnector) -> dict[str, str]:
    """Non-secret env values stored on the connector itself."""
    return {
        str(entry["name"]): str(entry.get("value") or "")
        for entry in (connector.env_json or [])
        if not entry.get("secret") and entry.get("value") is not None
    }


async def touch_last_used(session: AsyncSession, connector: GatewayMcpConnector) -> None:
    connector.last_used_at = utcnow()
    await session.commit()
