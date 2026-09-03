"""Connector CRUD, probe, tools, member switch and secrets (§2)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from gateway.auth import OrgRole
from gateway.mcp_connectors import oauth as oauth_mod
from gateway.mcp_connectors.probe import ProbeResult, parse_command, probe_command, probe_url
from gateway.mcp_connectors.slugs import SlugCollisionError
from gateway.mcp_connectors.ssrf import UnsafeUrlError, validate_remote_url
from gateway.mcp_connectors.tools import apply_tool_settings, merge_inventory
from gateway.mcp_connectors.upstream import pool as upstream_pool
from gateway.security.scope_guard import RequireScope
from gateway.store.mcp import ConnectorDraft, utcnow
from gateway.store.mcp import connectors as connector_store
from gateway.store.mcp import members as member_store
from gateway.store.mcp import policy as policy_store

from ..deps import StoreD
from .common import (
    caller,
    connector_to_dict,
    detail,
    is_admin,
    load_connector,
    member_state_to_dict,
    org_name_for,
    refresh_inventory,
    require_enabled,
    require_mutation_rights,
    signed_in_count_for,
)
from .schemas import ConnectorCreate, ConnectorPatch, MemberStateUpdate, ProbeRequest, SecretsUpdate, ToolsUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/connectors", dependencies=[RequireScope("read")])
async def list_connectors(request: Request, store: StoreD, role: OrgRole) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    rows = await connector_store.list_visible(store.session, org_id=org_id, user_id=user_id, is_admin=admin)
    members = await member_store.list_member_states(store.session, user_id=user_id, org_id=org_id)
    policy = await policy_store.get_policy(store.session, org_id=org_id)
    # Sign-in counts are an admin view of org connectors; everyone else sees 0.
    counts = await member_store.signed_in_counts(store.session, org_id=org_id) if admin else {}
    return {
        "connectors": [
            connector_to_dict(
                row,
                member=members.get(row.id),
                signed_in_count=counts.get(row.id, 0) if row.scope == "org" else 0,
            )
            for row in rows
        ],
        "policy": policy_store.policy_to_dict(policy),
        "is_admin": admin,
        "org_name": org_name_for(request),
    }


async def _probe(body: ProbeRequest, *, headers: dict[str, str] | None = None) -> ProbeResult:
    if body.url:
        try:
            return await probe_url(body.url, headers=headers)
        except UnsafeUrlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.command:
        return probe_command(body.command, body.args)
    raise HTTPException(status_code=422, detail="Provide a url or a command")


@router.post("/connectors/probe", dependencies=[RequireScope("write")])
async def probe_connector(body: ProbeRequest, store: StoreD) -> dict[str, Any]:
    require_enabled()
    caller(store)
    result = await _probe(body)
    return result.to_dict()


def _member_supplied(entry: dict[str, Any], *, scope: str) -> bool:
    # R2: org sandbox connectors never carry org-level secrets.
    return bool(entry.get("member_supplied")) or (scope == "org" and bool(entry.get("secret")))


@router.post("/connectors", status_code=201, dependencies=[RequireScope("write")])
async def create_connector(body: ConnectorCreate, store: StoreD, role: OrgRole) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    if body.scope == "org" and not admin:
        raise HTTPException(status_code=403, detail="Organization admin role required")
    if not body.url and not body.command:
        raise HTTPException(status_code=422, detail="Provide a url or a command")
    probe = await _probe(ProbeRequest(url=body.url, command=body.command, args=body.args), headers=body.headers)
    transport = body.transport or probe.transport
    if transport == "stdio" and body.url:
        raise HTTPException(status_code=422, detail="A sandbox connector needs a command, not a URL")
    if transport != "stdio" and not body.url:
        raise HTTPException(status_code=422, detail="A remote connector needs a URL")
    if transport == "stdio" and body.scope == "org" and any(e.secret and not e.member_supplied for e in body.env or []):
        logger.info("Org sandbox connector: secret env values are member-supplied (R2)")
    auth = body.auth or (probe.auth if probe.auth != "unknown" else "none")
    oauth_json = None
    client_secret = body.oauth_client.client_secret if body.oauth_client else None
    if auth == "oauth":
        discovery = probe.discovery
        if discovery is None and body.url:
            discovery = await oauth_mod.discover(body.url, probe.www_authenticate)
        if discovery is None:
            raise HTTPException(status_code=400, detail="This provider does not offer sign-in. Add a key instead.")
        oauth_json = oauth_mod.oauth_config(
            discovery,
            server_url=body.url or "",
            client_id=body.oauth_client.client_id if body.oauth_client else None,
            has_client_secret=bool(client_secret),
        )
    command, args = (None, [])
    if transport == "stdio":
        try:
            command, args = parse_command(body.command or "", body.args)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    env_entries = []
    secret_env: dict[str, str] = {}
    for entry in body.env or []:
        record = {
            "name": entry.name,
            "secret": bool(entry.secret),
            "member_supplied": _member_supplied(entry.model_dump(), scope=body.scope),
        }
        if entry.secret:
            if entry.value:
                secret_env[entry.name] = entry.value
        else:
            record["value"] = entry.value
        env_entries.append(record)
    url = None
    if body.url and transport != "stdio":
        try:
            url = await validate_remote_url(body.url)
        except UnsafeUrlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    draft = ConnectorDraft(
        scope=body.scope,
        name=body.name.strip(),
        transport=transport,
        created_by=user_id,
        owner_user_id=user_id if body.scope == "personal" else None,
        url=url,
        command=command,
        args=args,
        env=env_entries,
        header_names=sorted((body.headers or {}).keys()),
        auth=auth,
        oauth=oauth_json,
        headers=body.headers or None,
        oauth_client_secret=client_secret,
    )
    try:
        connector = await connector_store.create_connector(store.session, org_id=org_id, draft=draft)
    except SlugCollisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    member = None
    if secret_env:
        member = await member_store.ensure_member_state(
            store.session, org_id=org_id, connector_id=connector.id, user_id=user_id
        )
        member_store.set_member_secrets(member, env=secret_env)
        await store.session.commit()
    if probe.tools is not None and transport != "stdio":
        merged, _, _ = merge_inventory([], probe.tools, first_connect=True)
        connector.tools_json = merged
        connector.tools_hash = connector_store.tools_hash(merged)
        connector.protocol_version = probe.protocol_version
        connector.server_name = probe.server_name
        connector.status = "connected"
        connector.status_detail = None
        connector.updated_at = utcnow()
        await store.session.commit()
    else:
        await refresh_inventory(store.session, connector, member=member)
        if probe.error and connector.status in {"pending", "unreachable"}:
            connector.status = "unreachable"
            connector.status_detail = probe.error
            await store.session.commit()
    return connector_to_dict(connector, member=member)


@router.get("/connectors/{connector_id}", dependencies=[RequireScope("read")])
async def get_connector(connector_id: str, store: StoreD, role: OrgRole) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    connector = await load_connector(store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=admin)
    return await detail(store.session, connector, user_id=user_id, admin=admin)


@router.patch("/connectors/{connector_id}", dependencies=[RequireScope("write")])
async def patch_connector(connector_id: str, body: ConnectorPatch, store: StoreD, role: OrgRole) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    connector = await load_connector(store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=admin)
    require_mutation_rights(connector, user_id=user_id, admin=admin)
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields["name"] = body.name.strip()
    if body.enabled is not None:
        fields["enabled"] = body.enabled
    if body.url is not None:
        if connector.transport == "stdio":
            raise HTTPException(status_code=422, detail="A sandbox connector has no URL")
        try:
            fields["url"] = await validate_remote_url(body.url)
        except UnsafeUrlError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.command is not None or body.args is not None:
        if connector.transport != "stdio":
            raise HTTPException(status_code=422, detail="A remote connector has no command")
        try:
            command, args = parse_command(body.command or connector.command or "", body.args)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        fields["command"], fields["args_json"] = command, args
    if body.auth is not None and body.auth != connector.auth:
        if connector.transport == "stdio" and body.auth != "none":
            raise HTTPException(status_code=422, detail="Sandbox connectors use environment variables, not sign-in")
        fields["auth"] = body.auth
        if body.auth == "oauth":
            discovery = await oauth_mod.discover(fields.get("url") or connector.url or "")
            if discovery is None:
                raise HTTPException(status_code=400, detail="This provider does not offer sign-in. Add a key instead.")
            fields["oauth_json"] = oauth_mod.oauth_config(discovery, server_url=fields.get("url") or connector.url or "")
    await connector_store.update_connector(store.session, connector, **fields)
    await upstream_pool.evict_prefix(f"{connector.id}:")
    member = await member_store.get_member_state(store.session, connector_id=connector.id, user_id=user_id)
    if "url" in fields or "auth" in fields or "command" in fields:
        await refresh_inventory(store.session, connector, member=member)
    count = await signed_in_count_for(store.session, connector, admin=admin)
    return connector_to_dict(connector, member=member, signed_in_count=count)


@router.delete("/connectors/{connector_id}", status_code=204, dependencies=[RequireScope("write")])
async def delete_connector(connector_id: str, store: StoreD, role: OrgRole) -> Response:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    connector = await load_connector(store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=admin)
    require_mutation_rights(connector, user_id=user_id, admin=admin)
    await upstream_pool.evict_prefix(f"{connector.id}:")
    await connector_store.delete_connector(store.session, connector)
    return Response(status_code=204)


@router.post("/connectors/{connector_id}/refresh-tools", dependencies=[RequireScope("write")])
async def refresh_tools(connector_id: str, store: StoreD, role: OrgRole) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    connector = await load_connector(store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=admin)
    member = await member_store.get_member_state(store.session, connector_id=connector.id, user_id=user_id)
    await refresh_inventory(store.session, connector, member=member)
    count = await signed_in_count_for(store.session, connector, admin=admin)
    return connector_to_dict(connector, member=member, include_tools=True, signed_in_count=count)


@router.put("/connectors/{connector_id}/tools", dependencies=[RequireScope("write")])
async def update_tools(connector_id: str, body: ToolsUpdate, store: StoreD, role: OrgRole) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    connector = await load_connector(store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=admin)
    known = {tool["name"] for tool in connector.tools_json or []}
    unknown = sorted(set(body.tools) - known)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown tools: {', '.join(unknown[:5])}")
    manages_org_policy = connector.scope == "personal" or admin
    if connector.scope == "personal" and connector.owner_user_id != user_id and not admin:
        raise HTTPException(status_code=403, detail="Only the owner can change this connector")
    if manages_org_policy:
        settings = {name: {"enabled": s.enabled, "policy": s.policy} for name, s in body.tools.items()}
        tools = apply_tool_settings(list(connector.tools_json or []), settings)
        # Saving the inventory is the review: the added/removed badge counts reset.
        await connector_store.update_connector(
            store.session, connector, tools_json=tools, status="connected" if connector.status == "tools_changed" else connector.status,
            status_detail=None if connector.status == "tools_changed" else connector.status_detail,
            tools_added=0, tools_removed=0,
        )
        member = await member_store.get_member_state(store.session, connector_id=connector.id, user_id=user_id)
    else:
        # A member may only turn tools OFF for themselves on an org connector.
        member = await member_store.ensure_member_state(
            store.session, org_id=org_id, connector_id=connector.id, user_id=user_id
        )
        disabled = set(member.disabled_tools_json or [])
        for name, setting in body.tools.items():
            if setting.enabled and setting.policy != "off":
                disabled.discard(name)
            else:
                disabled.add(name)
        member.disabled_tools_json = sorted(disabled)
        member.updated_at = utcnow()
        await store.session.commit()
    count = await signed_in_count_for(store.session, connector, admin=admin)
    return connector_to_dict(connector, member=member, include_tools=True, signed_in_count=count)


@router.put("/connectors/{connector_id}/me", dependencies=[RequireScope("write")])
async def update_member_state(
    connector_id: str, body: MemberStateUpdate, store: StoreD, role: OrgRole
) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    connector = await load_connector(
        store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=is_admin(role)
    )
    member = await member_store.set_member_switch(
        store.session,
        org_id=org_id,
        connector_id=connector.id,
        user_id=user_id,
        enabled=body.enabled,
        disabled_tools=body.disabled_tools,
    )
    return member_state_to_dict(member)


@router.put("/connectors/{connector_id}/secrets", dependencies=[RequireScope("write")])
async def update_secrets(connector_id: str, body: SecretsUpdate, store: StoreD, role: OrgRole) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    connector = await load_connector(store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=admin)
    headers = {k.strip(): v for k, v in (body.headers or {}).items() if k.strip() and v}
    env = {k.strip(): v for k, v in (body.env or {}).items() if k.strip() and v}
    if not headers and not env:
        raise HTTPException(status_code=422, detail="Provide at least one header or env value")
    declared = {str(e["name"]): e for e in connector.env_json or []}
    member = await member_store.ensure_member_state(store.session, org_id=org_id, connector_id=connector.id, user_id=user_id)
    org_level_headers = connector.scope == "personal" and connector.owner_user_id == user_id
    if connector.scope == "org" and admin:
        org_level_headers = True
    if headers:
        if org_level_headers:
            merged = connector_store.static_headers(connector)
            merged.update(headers)
            connector_store.set_static_headers(connector, merged)
        else:
            member_store.set_member_secrets(member, headers=headers)
    member_env: dict[str, str] = {}
    for name, value in env.items():
        entry = declared.get(name)
        if entry is None:
            raise HTTPException(status_code=422, detail=f"Unknown environment variable: {name}")
        if entry.get("secret"):
            if connector.scope == "org" and not entry.get("member_supplied") and not admin:
                raise HTTPException(status_code=403, detail="Organization admin role required")
            member_env[name] = value
        else:
            if connector.scope == "org" and not admin:
                raise HTTPException(status_code=403, detail="Organization admin role required")
            entry["value"] = value
    if member_env:
        member_store.set_member_secrets(member, env=member_env)
    connector.env_json = [dict(e) for e in declared.values()]
    connector.updated_at = utcnow()
    await store.session.commit()
    await upstream_pool.evict_prefix(f"{connector.id}:")
    if connector.transport != "stdio":
        await refresh_inventory(store.session, connector, member=member)
    count = await signed_in_count_for(store.session, connector, admin=admin)
    return connector_to_dict(connector, member=member, signed_in_count=count)


@router.delete("/connectors/{connector_id}/secrets/{name}", dependencies=[RequireScope("write")])
async def delete_secret(connector_id: str, name: str, store: StoreD, role: OrgRole) -> dict[str, Any]:
    require_enabled()
    org_id, user_id = caller(store)
    admin = is_admin(role)
    connector = await load_connector(store.session, org_id=org_id, user_id=user_id, connector_id=connector_id, admin=admin)
    removed = False
    if connector.scope == "personal" and connector.owner_user_id == user_id or (connector.scope == "org" and admin):
        removed = connector_store.drop_static_header(connector, name) or removed
    member = await member_store.get_member_state(store.session, connector_id=connector.id, user_id=user_id)
    if member is not None:
        removed = member_store.drop_member_secret(member, name) or removed
    if not removed:
        raise HTTPException(status_code=404, detail="Secret not found")
    await store.session.commit()
    await upstream_pool.evict_prefix(f"{connector.id}:")
    count = await signed_in_count_for(store.session, connector, admin=admin)
    return connector_to_dict(connector, member=member, signed_in_count=count)
