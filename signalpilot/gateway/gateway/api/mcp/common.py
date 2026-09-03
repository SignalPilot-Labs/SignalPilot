"""Shared helpers for the Connectors API: gating, lookup, serialization, inventory refresh."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.auth.user import is_org_admin_role, org_name_from_claims
from gateway.db.models import GatewayMcpConnector, GatewayMcpMemberState
from gateway.mcp_connectors import policy as policy_mod
from gateway.mcp_connectors.probe import list_tools_via_sdk
from gateway.mcp_connectors.tools import merge_inventory, public_tool_info, tool_is_on
from gateway.mcp_connectors.upstream import UpstreamError, UpstreamSpec
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.store import Store
from gateway.store.mcp import connectors as connector_store
from gateway.store.mcp import iso, utcnow
from gateway.store.mcp import members as member_store

logger = logging.getLogger(__name__)


def require_enabled() -> None:
    if not enterprise_chat_feature_flags().mcp_connectors:
        raise HTTPException(status_code=404, detail="Connectors are not enabled for this deployment")


def is_admin(role: str) -> bool:
    return is_org_admin_role(role)


def caller(store: Store) -> tuple[str, str]:
    return store._require_org_id(), store.user_id or "local"


def org_name_for(request: Request) -> str | None:
    """Organization display name from the verified Clerk claims on this request, else None."""
    return org_name_from_claims(getattr(request.state, "_jwt_claims", None))


async def signed_in_count_for(session: AsyncSession, connector: GatewayMcpConnector, *, admin: bool) -> int:
    """Members signed in to an org connector. Admin-only; personal connectors and members see 0."""
    if not admin or connector.scope != "org":
        return 0
    return await member_store.count_signed_in(session, connector_id=connector.id)


def icon_url_for(connector: GatewayMcpConnector) -> str | None:
    """Gateway-relative icon route for remote connectors (the web CSP blocks provider hosts)."""
    if connector.transport == "stdio" or not connector.url:
        return None
    return f"/api/mcp/connectors/{connector.id}/icon"


async def load_connector(
    session: AsyncSession, *, org_id: str, user_id: str, connector_id: str, admin: bool
) -> GatewayMcpConnector:
    connector = await connector_store.get_connector(session, org_id=org_id, connector_id=connector_id)
    if connector is None or not connector_store.is_visible_to(connector, user_id=user_id, is_admin=admin):
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


def require_mutation_rights(connector: GatewayMcpConnector, *, user_id: str, admin: bool) -> None:
    """Org connectors need an org admin; personal ones their owner (admins may manage all)."""
    if connector.scope == "org":
        if not admin:
            raise HTTPException(status_code=403, detail="Organization admin role required")
        return
    if connector.owner_user_id != user_id and not admin:
        raise HTTPException(status_code=403, detail="Only the owner can change this connector")


def member_state_to_dict(member: GatewayMcpMemberState | None) -> dict[str, Any]:
    if member is None:
        return {
            "enabled": True,
            "disabled_tools": [],
            "signed_in": False,
            "has_key": False,
            "signed_in_at": None,
            "account_label": None,
        }
    tokens = member_store.oauth_tokens(member)
    has_key = bool(member_store.member_headers(member) or member_store.member_env(member))
    return {
        "enabled": bool(member.enabled),
        "disabled_tools": list(member.disabled_tools_json or []),
        "signed_in": tokens is not None,
        "has_key": has_key,
        "signed_in_at": iso(member.signed_in_at) if tokens else None,
        "account_label": (member.account_label or None) if tokens else None,
    }


def connector_to_dict(
    connector: GatewayMcpConnector,
    *,
    member: GatewayMcpMemberState | None,
    include_tools: bool = False,
    signed_in_count: int = 0,
) -> dict[str, Any]:
    static = connector_store.static_headers(connector)
    mine_headers = member_store.member_headers(member)
    mine_env = member_store.member_env(member)
    header_names = sorted(set(connector.header_names_json or []) | set(static) | set(mine_headers))
    env_keys = []
    for entry in connector.env_json or []:
        name = str(entry.get("name"))
        secret = bool(entry.get("secret"))
        has_value = (name in mine_env) if secret else (entry.get("value") is not None)
        env_keys.append(
            {
                "name": name,
                "secret": secret,
                "has_value": bool(has_value),
                "member_supplied": bool(entry.get("member_supplied")),
            }
        )
    tools = list(connector.tools_json or [])
    payload: dict[str, Any] = {
        "id": connector.id,
        "org_id": connector.org_id,
        "scope": connector.scope,
        "owner_user_id": connector.owner_user_id,
        "name": connector.name,
        "slug": connector.slug,
        "transport": connector.transport,
        "url": connector.url,
        "command": connector.command,
        "args": list(connector.args_json or []),
        "env_keys": env_keys,
        "header_keys": [{"name": n, "has_value": n in static or n in mine_headers} for n in header_names],
        "auth": connector.auth,
        "status": connector.status,
        "status_detail": connector.status_detail,
        "protocol_version": connector.protocol_version,
        "server_name": connector.server_name,
        "enabled": bool(connector.enabled),
        "tool_count": len(tools),
        "enabled_tool_count": sum(1 for tool in tools if tool_is_on(tool)),
        "tools_added": int(connector.tools_added or 0),
        "tools_removed": int(connector.tools_removed or 0),
        "signed_in_count": int(signed_in_count),
        "icon_url": icon_url_for(connector),
        "created_by": connector.created_by,
        "created_at": iso(connector.created_at),
        "updated_at": iso(connector.updated_at),
        "last_used_at": iso(connector.last_used_at),
        "my_state": member_state_to_dict(member),
    }
    if include_tools:
        payload["tools"] = [public_tool_info(tool) for tool in tools]
    return payload


def status_for_missing_credentials(connector: GatewayMcpConnector, member: GatewayMcpMemberState | None) -> str | None:
    return policy_mod.credentials_ready(connector, member)


async def refresh_inventory(
    session: AsyncSession,
    connector: GatewayMcpConnector,
    *,
    member: GatewayMcpMemberState | None,
    client_factory=None,
) -> tuple[list[str], list[str]]:
    """Re-list tools upstream with the caller's credential and merge (new tools off).

    Updates status/status_detail/protocol_version/server_name/tools/hash on the
    connector and commits. ``tools_added``/``tools_removed`` accumulate until
    the inventory is reviewed (PUT /tools). Returns (added, removed) tool names.
    """
    if connector.transport == "stdio":
        connector.status = "connected" if connector.status == "pending" else connector.status
        connector.status_detail = "Tools for sandbox connectors are discovered when a chat starts"
        connector.updated_at = utcnow()
        await session.commit()
        return [], []
    missing = status_for_missing_credentials(connector, member)
    if missing:
        connector.status = missing
        connector.status_detail = None
        connector.updated_at = utcnow()
        await session.commit()
        return [], []
    spec = UpstreamSpec(
        url=connector.url or "",
        transport="sse" if connector.transport == "sse" else "http",
        headers=policy_mod.upstream_headers(connector, member),
    )
    try:
        upstream_tools, protocol_version, server_name = await list_tools_via_sdk(spec, client_factory=client_factory)
    except UpstreamError as exc:
        if exc.status == 401:
            connector.status = "needs_sign_in" if connector.auth == "oauth" else "needs_key"
            connector.status_detail = "The provider rejected the key" if connector.auth != "oauth" else "Sign in again"
        else:
            connector.status = "unreachable"
            connector.status_detail = str(exc)[:500]
        connector.updated_at = utcnow()
        await session.commit()
        return [], []
    existing = list(connector.tools_json or [])
    merged, added, removed = merge_inventory(existing, upstream_tools, first_connect=not existing)
    new_hash = connector_store.tools_hash(merged)
    changed = bool(existing) and connector.tools_hash is not None and new_hash != connector.tools_hash
    connector.tools_json = merged
    connector.tools_hash = new_hash
    if added or removed:
        connector.tools_added = int(connector.tools_added or 0) + len(added)
        connector.tools_removed = int(connector.tools_removed or 0) + len(removed)
    connector.protocol_version = protocol_version
    connector.server_name = server_name or connector.server_name
    connector.status = "tools_changed" if changed and (added or removed) else "connected"
    connector.status_detail = (
        f"{len(added)} added, {len(removed)} removed" if connector.status == "tools_changed" else None
    )
    connector.updated_at = utcnow()
    await session.commit()
    return added, removed


async def detail(
    session: AsyncSession, connector: GatewayMcpConnector, *, user_id: str, admin: bool = False
) -> dict[str, Any]:
    member = await member_store.get_member_state(session, connector_id=connector.id, user_id=user_id)
    count = await signed_in_count_for(session, connector, admin=admin)
    return connector_to_dict(connector, member=member, include_tools=True, signed_in_count=count)
