"""Policy resolution: which connectors and tools a caller gets (R3, R4), per run and per call."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from gateway.db.models import GatewayMcpConnector, GatewayMcpMemberState, GatewayMcpOrgPolicy
from gateway.mcp_connectors.ssrf import host_of
from gateway.mcp_connectors.tools import allowed_tool_names
from gateway.store.mcp import connectors as connector_store
from gateway.store.mcp import members as member_store
from gateway.store.mcp import policy as policy_store

INJECTABLE_STATUSES = frozenset({"connected", "tools_changed", "needs_sign_in", "needs_key"})


def host_allowed(host: str, allowed_hosts: list[str]) -> bool:
    """Empty list = any public host; otherwise fnmatch globs against the host."""
    if not allowed_hosts:
        return True
    host = host.lower()
    return any(fnmatch.fnmatchcase(host, pattern.lower()) for pattern in allowed_hosts if pattern)


@dataclass(frozen=True)
class Access:
    allowed_tools: list[str]
    reason: str | None = None  # None when usable

    @property
    def usable(self) -> bool:
        return self.reason is None


def credentials_ready(connector: GatewayMcpConnector, member: GatewayMcpMemberState | None) -> str | None:
    """None when the caller has what the connector needs, else the status word."""
    if connector.auth == "oauth":
        return None if member_store.oauth_tokens(member) else "needs_sign_in"
    if connector.auth == "key":
        static = connector_store.static_headers(connector)
        mine = member_store.member_headers(member)
        return None if (static or mine) else "needs_key"
    if connector.transport == "stdio":
        secret_names = {str(e["name"]) for e in (connector.env_json or []) if e.get("secret")}
        mine = member_store.member_env(member)
        return None if secret_names <= set(mine) else "needs_key"
    return None


def evaluate_access(
    connector: GatewayMcpConnector,
    *,
    member: GatewayMcpMemberState | None,
    policy: GatewayMcpOrgPolicy | None,
    run_origin: str = "user",
) -> Access:
    """Decide whether this caller may use the connector and with which tools."""
    if not connector.enabled:
        return Access([], "disabled")
    if connector.status not in INJECTABLE_STATUSES:
        return Access([], connector.status or "pending")
    if connector.scope == "personal":
        if policy is not None and not policy.allow_personal:
            return Access([], "personal_not_allowed")
        if connector.url and not host_allowed(host_of(connector.url), list((policy.allowed_hosts_json if policy else []) or [])):
            return Access([], "host_not_allowed")
    if member is not None and not member.enabled:
        return Access([], "off_for_me")
    missing = credentials_ready(connector, member)
    if missing:
        return Access([], missing)
    tools = allowed_tool_names(
        list(connector.tools_json or []),
        member_disabled=list(member.disabled_tools_json or []) if member else [],
        run_origin=run_origin,
    )
    if not tools:
        return Access([], "no_tools")
    return Access(tools)


def upstream_headers(connector: GatewayMcpConnector, member: GatewayMcpMemberState | None) -> dict[str, str]:
    """Static org/owner headers, then member-supplied headers, then the member's OAuth bearer."""
    headers = connector_store.static_headers(connector)
    headers.update(member_store.member_headers(member))
    tokens = member_store.oauth_tokens(member)
    if tokens:
        headers["Authorization"] = f"{tokens.get('token_type') or 'Bearer'} {tokens['access_token']}"
    return headers


def _dedupe_slug(slug: str, taken: set[str]) -> str:
    if slug not in taken:
        return slug
    candidate = slug[:35].rstrip("_") + "_mine"
    counter = 2
    while candidate in taken:
        candidate = f"{slug[:33].rstrip('_')}_mine{counter}"
        counter += 1
    return candidate


async def resolve_injection(
    session: AsyncSession,
    *,
    org_id: str,
    user_id: str,
    run_origin: str,
    proxy_base_url: str,
) -> list[dict[str, Any]]:
    """Build ``payload["mcp_connectors"]`` (§4) for one run."""
    connectors = await connector_store.list_effective(session, org_id=org_id, user_id=user_id)
    policy = await policy_store.get_policy(session, org_id=org_id)
    members = await member_store.list_member_states(session, user_id=user_id, org_id=org_id)
    entries: list[dict[str, Any]] = []
    taken: set[str] = set()
    ordered = sorted(connectors, key=lambda c: (0 if c.scope == "org" else 1, c.name))
    for connector in ordered:
        member = members.get(connector.id)
        access = evaluate_access(connector, member=member, policy=policy, run_origin=run_origin)
        if not access.usable:
            continue
        slug = _dedupe_slug(connector.slug, taken)
        taken.add(slug)
        if connector.transport == "stdio":
            env = connector_store.public_env(connector)
            env.update(member_store.member_env(member))
            entries.append(
                {
                    "slug": slug,
                    "kind": "sandbox",
                    "command": connector.command or "",
                    "args": list(connector.args_json or []),
                    "env": env,
                    "allowed_tools": access.allowed_tools,
                }
            )
        else:
            entries.append(
                {
                    "slug": slug,
                    "kind": "remote",
                    "url": f"{proxy_base_url.rstrip('/')}/api/mcp/proxy/{connector.id}/mcp",
                    "allowed_tools": access.allowed_tools,
                }
            )
    return entries


async def access_for_call(
    session: AsyncSession,
    *,
    connector: GatewayMcpConnector,
    user_id: str,
    run_origin: str,
) -> tuple[Access, GatewayMcpMemberState | None, GatewayMcpOrgPolicy | None]:
    """Fresh per-call decision (defense in depth for the proxy)."""
    member = await member_store.get_member_state(session, connector_id=connector.id, user_id=user_id)
    policy = await policy_store.get_policy(session, org_id=connector.org_id)
    return evaluate_access(connector, member=member, policy=policy, run_origin=run_origin), member, policy


def proxy_base_url() -> str:
    from gateway.config.gateway import get_gateway_settings

    return get_gateway_settings().sp_public_gateway_url.rstrip("/")
