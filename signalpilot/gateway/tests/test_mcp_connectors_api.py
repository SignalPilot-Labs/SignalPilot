"""Connectors API (§2): CRUD, scope isolation, admin gating, slug rule, probe SSRF, secrets, OAuth state."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from gateway.api import mcp as mcp_api
from gateway.api.mcp import common as api_common
from gateway.api.mcp import connectors as connectors_api
from gateway.api.mcp import oauth as oauth_api
from gateway.api.mcp.schemas import ConnectorListOut, ConnectorOut, ToolCallOut
from gateway.mcp_connectors import oauth as oauth_mod
from gateway.mcp_connectors.probe import ProbeResult
from gateway.mcp_connectors.tools import tool_info_from_upstream
from gateway.store.mcp import members as member_store

from .mcp_connectors_support import BASE, Harness, create_connector, harness, probe_ok, tool_stub

_tool = tool_stub
_probe_ok = probe_ok
_create = create_connector


def _id_token(claims: dict[str, Any]) -> str:
    """An unsigned JWT-shaped id_token; only the payload segment is read."""
    segment = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{segment}.signature"


# ── CRUD, defaults and contract shape ────────────────────────────────────────


def test_create_personal_connector_seeds_tool_defaults_and_contract_fields(harness: Harness) -> None:
    h = harness.as_user("user-a")
    created = _create(h)
    assert created["slug"] == "vendor_docs" and created["scope"] == "personal" and created["owner_user_id"] == "user-a"
    assert created["status"] == "connected" and created["transport"] == "http" and created["auth"] == "none"
    assert created["tool_count"] == 3 and created["enabled_tool_count"] == 1
    assert created["protocol_version"] == "2025-11-25" and created["server_name"] == "Vendor Docs"
    assert created["my_state"] == {
        "enabled": True,
        "disabled_tools": [],
        "signed_in": False,
        "has_key": False,
        "signed_in_at": None,
        "account_label": None,
    }
    expected_keys = {
        "id", "org_id", "scope", "owner_user_id", "name", "slug", "transport", "url", "command", "args", "env_keys",
        "header_keys", "auth", "status", "status_detail", "protocol_version", "server_name", "enabled", "tool_count",
        "enabled_tool_count", "tools_added", "tools_removed", "signed_in_count", "icon_url", "created_by",
        "created_at", "updated_at", "last_used_at", "my_state",
    }
    assert set(created) == expected_keys
    assert created["tools_added"] == 0 and created["tools_removed"] == 0 and created["signed_in_count"] == 0
    assert created["icon_url"] == f"/api/mcp/connectors/{created['id']}/icon"
    ConnectorOut.model_validate(created)

    detail = h.client.get(f"{BASE}/connectors/{created['id']}").json()
    ConnectorOut.model_validate(detail)
    by_name = {t["name"]: t for t in detail["tools"]}
    assert by_name["search"]["enabled"] is True and by_name["search"]["policy"] == "auto"
    assert by_name["delete_page"]["enabled"] is False and by_name["delete_page"]["policy"] == "off"
    assert by_name["create_page"]["enabled"] is False  # no readOnlyHint -> off until turned on
    assert set(by_name["search"]) == {
        "name", "title", "description", "annotations", "enabled", "policy", "discovered_at", "is_new"
    }
    listing = h.client.get(f"{BASE}/connectors").json()
    assert set(listing) == {"connectors", "policy", "is_admin", "org_name"} and listing["is_admin"] is False
    assert listing["policy"] == {"allow_personal": True, "allowed_hosts": [], "updated_at": None}
    assert listing["org_name"] is None  # local mode: no Clerk organization claims
    ConnectorListOut.model_validate(listing)


def test_list_reports_org_name_from_clerk_claims(harness: Harness) -> None:
    from gateway.security import scope_guard

    async def _with_claims(request: Request) -> str:
        request.state._jwt_claims = {"sub": "user-a", "o": {"id": "org_1", "rol": "admin", "slg": "acme"}}
        return "user-a"

    harness.client.app.dependency_overrides[scope_guard._resolve_user_id] = _with_claims
    assert harness.client.get(f"{BASE}/connectors").json()["org_name"] == "acme"  # slug fallback

    async def _with_name(request: Request) -> str:
        request.state._jwt_claims = {"sub": "user-a", "org_id": "org_1", "org_name": "Acme Inc"}
        return "user-a"

    harness.client.app.dependency_overrides[scope_guard._resolve_user_id] = _with_name
    assert harness.client.get(f"{BASE}/connectors").json()["org_name"] == "Acme Inc"


def test_signed_in_count_is_admin_only_and_org_only(harness: Harness) -> None:
    admin = harness.as_user("admin-a", "admin")
    org = _create(admin, scope="org", name="Jira", url="https://mcp.jira.example/mcp")
    personal = _create(admin, name="Mine")

    async def _member(user_id: str, *, tokens: dict[str, Any] | None = None, env: dict[str, str] | None = None):
        async with harness.session_factory() as session:
            row = await member_store.ensure_member_state(session, org_id="local", connector_id=org["id"], user_id=user_id)
            if tokens:
                member_store.set_oauth_tokens(row, tokens, account_label="ada@example.com")
            if env:
                member_store.set_member_secrets(row, env=env)
            await session.commit()

    asyncio.run(_member("user-a", tokens={"access_token": "at", "refresh_token": None, "expires_at": None}))
    asyncio.run(_member("user-b", env={"TOKEN": "x"}))
    asyncio.run(_member("user-c"))  # a row without any credential is not "signed in"
    asyncio.run(_member("admin-a", tokens={"access_token": "at2", "refresh_token": None, "expires_at": None}))

    listing = admin.client.get(f"{BASE}/connectors").json()
    counts = {c["name"]: c["signed_in_count"] for c in listing["connectors"]}
    assert counts == {"Jira": 3, "Mine": 0}
    assert admin.client.get(f"{BASE}/connectors/{org['id']}").json()["signed_in_count"] == 3
    assert admin.client.get(f"{BASE}/connectors/{personal['id']}").json()["signed_in_count"] == 0

    member = harness.as_user("user-a")
    assert member.client.get(f"{BASE}/connectors").json()["connectors"][0]["signed_in_count"] == 0
    detail = member.client.get(f"{BASE}/connectors/{org['id']}").json()
    assert detail["signed_in_count"] == 0
    assert detail["my_state"]["signed_in"] is True and detail["my_state"]["account_label"] == "ada@example.com"
    assert harness.as_user("user-b").client.get(f"{BASE}/connectors/{org['id']}").json()["my_state"]["account_label"] is None


def test_patch_and_delete_personal_connector(harness: Harness) -> None:
    h = harness.as_user("user-a")
    created = _create(h)
    patched = h.client.patch(f"{BASE}/connectors/{created['id']}", json={"name": "Docs v2", "enabled": False})
    assert patched.status_code == 200 and patched.json()["name"] == "Docs v2" and patched.json()["enabled"] is False
    assert patched.json()["slug"] == "vendor_docs"  # slugs never change after creation
    assert h.client.delete(f"{BASE}/connectors/{created['id']}").status_code == 204
    assert h.client.get(f"{BASE}/connectors/{created['id']}").status_code == 404


# ── Isolation and admin gating ───────────────────────────────────────────────


def test_personal_connectors_are_isolated_and_admins_see_everything(harness: Harness) -> None:
    mine = _create(harness.as_user("user-a"))
    other_view = harness.as_user("user-b").client.get(f"{BASE}/connectors").json()
    assert other_view["connectors"] == []
    assert harness.client.get(f"{BASE}/connectors/{mine['id']}").status_code == 404
    assert harness.client.patch(f"{BASE}/connectors/{mine['id']}", json={"name": "x"}).status_code == 404
    admin_view = harness.as_user("admin-a", "admin").client.get(f"{BASE}/connectors").json()
    assert [c["id"] for c in admin_view["connectors"]] == [mine["id"]] and admin_view["is_admin"] is True


def test_org_mutations_require_admin_and_members_keep_own_switch(harness: Harness) -> None:
    member = harness.as_user("user-a")
    denied = member.client.post(
        f"{BASE}/connectors", json={"scope": "org", "name": "Jira", "url": "https://mcp.jira.example/mcp"}
    )
    assert denied.status_code == 403
    org = _create(harness.as_user("admin-a", "admin"), scope="org", name="Jira", url="https://mcp.jira.example/mcp")
    assert org["owner_user_id"] is None and org["scope"] == "org"

    member = harness.as_user("user-a")
    assert member.client.patch(f"{BASE}/connectors/{org['id']}", json={"enabled": False}).status_code == 403
    assert member.client.delete(f"{BASE}/connectors/{org['id']}").status_code == 403
    assert member.client.put(f"{BASE}/policy", json={"allow_personal": False, "allowed_hosts": []}).status_code == 403
    assert member.client.get(f"{BASE}/activity").status_code == 403

    # A member sees the org connector and may only tighten it for themselves.
    seen = member.client.get(f"{BASE}/connectors").json()["connectors"]
    assert [c["id"] for c in seen] == [org["id"]]
    me = member.client.put(f"{BASE}/connectors/{org['id']}/me", json={"enabled": False, "disabled_tools": ["search"]})
    assert me.status_code == 200 and me.json() == {
        "enabled": False, "disabled_tools": ["search"], "signed_in": False, "has_key": False, "signed_in_at": None,
        "account_label": None,
    }
    tools = member.client.put(
        f"{BASE}/connectors/{org['id']}/tools",
        json={"tools": {"delete_page": {"enabled": True, "policy": "auto"}, "search": {"enabled": False, "policy": "off"}}},
    )
    assert tools.status_code == 200
    body = tools.json()
    # Org-level decision unchanged; the member's OFF landed in member state.
    assert {t["name"]: t["enabled"] for t in body["tools"]}["delete_page"] is False
    assert body["my_state"]["disabled_tools"] == ["search"]

    admin = harness.as_user("admin-a", "admin")
    changed = admin.client.put(
        f"{BASE}/connectors/{org['id']}/tools", json={"tools": {"delete_page": {"enabled": True, "policy": "auto"}}}
    )
    assert {t["name"]: t["enabled"] for t in changed.json()["tools"]}["delete_page"] is True
    assert admin.client.delete(f"{BASE}/connectors/{org['id']}").status_code == 204


# ── Slug rule R9 ─────────────────────────────────────────────────────────────


def test_slug_collision_rule(harness: Harness) -> None:
    org = _create(harness.as_user("admin-a", "admin"), scope="org", name="GitHub", url="https://mcp.github.example/mcp")
    assert org["slug"] == "github"
    personal = _create(harness.as_user("user-a"), name="GitHub", url="https://mcp.github.example/mcp")
    assert personal["slug"] == "github_mine"
    duplicate = harness.client.post(
        f"{BASE}/connectors", json={"scope": "personal", "name": "GitHub", "url": "https://mcp.github.example/mcp"}
    )
    assert duplicate.status_code == 409
    # Another user may own the same personal slug.
    assert _create(harness.as_user("user-b"), name="GitHub", url="https://mcp.github.example/mcp")["slug"] == "github_mine"
    # Removing the org connector renames nothing.
    assert harness.as_user("admin-a", "admin").client.delete(f"{BASE}/connectors/{org['id']}").status_code == 204
    assert harness.as_user("user-a").client.get(f"{BASE}/connectors/{personal['id']}").json()["slug"] == "github_mine"


# ── Probe SSRF (R8) ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    ["https://169.254.169.254/latest/meta-data/", "https://10.0.0.5/mcp", "https://192.168.1.1/mcp", "https://[fc00::1]/mcp"],
)
def test_probe_rejects_private_ranges(harness: Harness, monkeypatch, url: str) -> None:
    from gateway.mcp_connectors.probe import probe_url as real_probe

    monkeypatch.setattr(connectors_api, "probe_url", real_probe)
    response = harness.client.post(f"{BASE}/connectors/probe", json={"url": url})
    assert response.status_code == 400 and "private" in response.json()["detail"].lower()


def test_probe_rejects_plain_http_in_cloud_mode(harness: Harness, monkeypatch) -> None:
    from gateway.mcp_connectors import ssrf
    from gateway.mcp_connectors.probe import probe_url as real_probe

    monkeypatch.setattr(connectors_api, "probe_url", real_probe)
    monkeypatch.setattr(ssrf, "is_cloud_mode", lambda: True)
    response = harness.client.post(f"{BASE}/connectors/probe", json={"url": "http://localhost:3001/mcp"})
    assert response.status_code == 400 and "https" in response.json()["detail"].lower()
    assert harness.client.post(f"{BASE}/connectors/probe", json={}).status_code == 422


def test_probe_command_returns_stdio(harness: Harness) -> None:
    response = harness.client.post(f"{BASE}/connectors/probe", json={"command": "npx -y @modelcontextprotocol/server-everything"})
    assert response.status_code == 200 and response.json() == {"transport": "stdio", "auth": "none", "server_name": "npx"}


# ── Refresh: new tools off ───────────────────────────────────────────────────


def test_refresh_tools_marks_new_tools_off_and_status_tools_changed(harness: Harness, monkeypatch) -> None:
    h = harness.as_user("user-a")
    created = _create(h)

    async def fake_list(spec, client_factory=None):
        return (
            [
                tool_info_from_upstream(_tool("search", readOnlyHint=True)),
                tool_info_from_upstream(_tool("list_pages", readOnlyHint=True)),
            ],
            "2025-11-25",
            "Vendor Docs",
        )

    monkeypatch.setattr(api_common, "list_tools_via_sdk", fake_list)
    refreshed = h.client.post(f"{BASE}/connectors/{created['id']}/refresh-tools")
    assert refreshed.status_code == 200
    body = refreshed.json()
    by_name = {t["name"]: t for t in body["tools"]}
    assert body["status"] == "tools_changed" and body["status_detail"] == "1 added, 2 removed"
    assert body["tools_added"] == 1 and body["tools_removed"] == 2
    assert by_name["search"]["enabled"] is True
    assert by_name["list_pages"]["enabled"] is False and by_name["list_pages"]["is_new"] is True
    assert "delete_page" not in by_name

    # A second refresh before review accumulates rather than overwriting.
    async def fake_list_again(spec, client_factory=None):
        return ([tool_info_from_upstream(_tool("list_pages", readOnlyHint=True))], "2025-11-25", "Vendor Docs")

    monkeypatch.setattr(api_common, "list_tools_via_sdk", fake_list_again)
    again = h.client.post(f"{BASE}/connectors/{created['id']}/refresh-tools").json()
    assert again["tools_added"] == 1 and again["tools_removed"] == 3
    assert h.client.get(f"{BASE}/connectors").json()["connectors"][0]["tools_removed"] == 3

    # Reviewing (PUT tools) clears the badge and the counters.
    reviewed = h.client.put(
        f"{BASE}/connectors/{created['id']}/tools", json={"tools": {"list_pages": {"enabled": True, "policy": "auto"}}}
    ).json()
    assert reviewed["status"] == "connected" and {t["name"]: t["is_new"] for t in reviewed["tools"]}["list_pages"] is False
    assert reviewed["tools_added"] == 0 and reviewed["tools_removed"] == 0
    # A member turning tools off for themselves on an org connector is not a review.
    org = _create(harness.as_user("admin-a", "admin"), scope="org", name="Jira", url="https://mcp.jira.example/mcp")
    monkeypatch.setattr(api_common, "list_tools_via_sdk", fake_list)
    assert harness.client.post(f"{BASE}/connectors/{org['id']}/refresh-tools").json()["tools_added"] == 1
    member_view = harness.as_user("user-a").client.put(
        f"{BASE}/connectors/{org['id']}/tools", json={"tools": {"search": {"enabled": False, "policy": "off"}}}
    ).json()
    assert member_view["tools_added"] == 1


# ── Secrets are write-only ───────────────────────────────────────────────────


def test_secrets_are_write_only_and_rotatable(harness: Harness, monkeypatch) -> None:
    h = harness.as_user("user-a")
    created = _create(
        h,
        headers={"X-API-Key": "sk-live-SECRET-VALUE"},
        env=[{"name": "TOKEN", "value": "env-SECRET", "secret": True}, {"name": "REGION", "value": "us", "secret": False}],
    )
    assert "SECRET" not in h.client.get(f"{BASE}/connectors/{created['id']}").text
    assert created["header_keys"] == [{"name": "X-API-Key", "has_value": True}]
    assert created["auth"] == "key"
    assert {e["name"]: e for e in created["env_keys"]}["TOKEN"] == {
        "name": "TOKEN", "secret": True, "has_value": True, "member_supplied": False,
    }
    assert {e["name"]: e for e in created["env_keys"]}["REGION"]["has_value"] is True

    async def fake_list(spec, client_factory=None):
        assert spec.headers["X-API-Key"] == "rotated-SECRET"
        return ([tool_info_from_upstream(_tool("search", readOnlyHint=True))], "2025-11-25", "Vendor Docs")

    monkeypatch.setattr(api_common, "list_tools_via_sdk", fake_list)
    rotated = h.client.put(f"{BASE}/connectors/{created['id']}/secrets", json={"headers": {"X-API-Key": "rotated-SECRET"}})
    assert rotated.status_code == 200 and "SECRET" not in rotated.text
    assert rotated.json()["header_keys"] == [{"name": "X-API-Key", "has_value": True}]
    assert h.client.put(f"{BASE}/connectors/{created['id']}/secrets", json={}).status_code == 422
    assert h.client.put(f"{BASE}/connectors/{created['id']}/secrets", json={"env": {"NOPE": "x"}}).status_code == 422

    removed = h.client.delete(f"{BASE}/connectors/{created['id']}/secrets/X-API-Key")
    assert removed.status_code == 200 and removed.json()["header_keys"] == []
    assert h.client.delete(f"{BASE}/connectors/{created['id']}/secrets/X-API-Key").status_code == 404


def test_org_sandbox_secret_env_is_member_supplied(harness: Harness) -> None:
    admin = harness.as_user("admin-a", "admin")
    created = _create(
        admin,
        scope="org",
        name="GitHub",
        url=None,
        command="npx -y @modelcontextprotocol/server-github",
        env=[{"name": "GITHUB_TOKEN", "secret": True, "member_supplied": False}],
    )
    assert created["transport"] == "stdio" and created["command"] == "npx"
    assert created["args"] == ["-y", "@modelcontextprotocol/server-github"]
    assert created["env_keys"] == [{"name": "GITHUB_TOKEN", "secret": True, "has_value": False, "member_supplied": True}]
    member = harness.as_user("user-a")
    saved = member.client.put(f"{BASE}/connectors/{created['id']}/secrets", json={"env": {"GITHUB_TOKEN": "ghp_SECRET"}})
    assert saved.status_code == 200 and "ghp_" not in saved.text
    assert saved.json()["env_keys"][0]["has_value"] is True and saved.json()["my_state"]["has_key"] is True
    # The admin's view has no value: member-supplied secrets are per member.
    assert harness.as_user("admin-a", "admin").client.get(f"{BASE}/connectors/{created['id']}").json()["env_keys"][0][
        "has_value"
    ] is False


# ── Policy and activity ──────────────────────────────────────────────────────


def test_policy_roundtrip(harness: Harness) -> None:
    admin = harness.as_user("admin-a", "admin")
    assert admin.client.get(f"{BASE}/policy").json() == {"allow_personal": True, "allowed_hosts": [], "updated_at": None}
    updated = admin.client.put(f"{BASE}/policy", json={"allow_personal": False, "allowed_hosts": ["*.Linear.app"]})
    assert updated.status_code == 200
    assert updated.json()["allow_personal"] is False and updated.json()["allowed_hosts"] == ["*.linear.app"]
    assert updated.json()["updated_at"] is not None
    assert harness.as_user("user-a").client.get(f"{BASE}/policy").json()["allow_personal"] is False


def test_activity_endpoints_shape(harness: Harness) -> None:
    h = harness.as_user("user-a")
    created = _create(h)
    assert h.client.get(f"{BASE}/connectors/{created['id']}/activity").json() == {"calls": []}
    assert harness.as_user("admin-a", "admin").client.get(f"{BASE}/activity?limit=10").json() == {"calls": []}

    from gateway.store.mcp import tool_calls as audit_store

    async def _record():
        async with harness.session_factory() as session:
            await audit_store.record_call(
                session, org_id="local", connector_id=created["id"], user_id="user-a", tool="search", outcome="ok",
                duration_ms=12, run_id="run-1", conversation_id="conv-1", error=None,
            )

    asyncio.run(_record())
    calls = harness.as_user("admin-a", "admin").client.get(f"{BASE}/activity").json()["calls"]
    assert len(calls) == 1 and calls[0]["user_id"] == "user-a" and calls[0]["user_label"] is None
    ToolCallOut.model_validate(calls[0])


def test_feature_flag_off_hides_api(harness: Harness, monkeypatch) -> None:
    monkeypatch.setenv("SP_FEATURE_CHAT_MCP_CONNECTORS", "false")
    assert harness.client.get(f"{BASE}/connectors").status_code == 404
    assert harness.client.get(f"{BASE}/oauth/client-metadata.json").status_code == 200


# ── OAuth state round trip (R6) ──────────────────────────────────────────────


async def _oauth_probe(url: str, **_kwargs) -> ProbeResult:
    discovery = oauth_mod.OAuthDiscovery(
        issuer="https://as.example.com",
        metadata_url="https://as.example.com/.well-known/oauth-authorization-server",
        metadata={
            "issuer": "https://as.example.com",
            "authorization_endpoint": "https://as.example.com/authorize",
            "token_endpoint": "https://as.example.com/token",
            "client_id_metadata_document_supported": True,
        },
        resource_metadata={"scopes_supported": ["docs:read"]},
        scopes="docs:read",
        registration="cimd",
    )
    return ProbeResult(
        transport="http",
        auth="oauth",
        oauth={"authorization_server": "https://as.example.com", "registration": "cimd"},
        discovery=discovery,
    )


def test_oauth_state_round_trip(harness: Harness, monkeypatch) -> None:
    monkeypatch.setattr(connectors_api, "probe_url", _oauth_probe)
    monkeypatch.setenv("SP_MCP_OAUTH_PUBLIC_URL", "https://gw.example.com")
    monkeypatch.setenv("SP_WEB_URL", "https://app.example.com")
    h = harness.as_user("user-a")
    probe = h.client.post(f"{BASE}/connectors/probe", json={"url": "https://mcp.vendor.example/mcp"}).json()
    assert probe == {
        "transport": "http", "auth": "oauth", "oauth": {"authorization_server": "https://as.example.com", "registration": "cimd"},
    }
    created = _create(h, name="Vendor")
    assert created["auth"] == "oauth" and created["status"] == "needs_sign_in" and created["tool_count"] == 0

    start = h.client.get(
        f"{BASE}/connectors/{created['id']}/oauth/start", params={"redirect_after": "/settings/connectors?tab=access"},
        follow_redirects=False,
    )
    assert start.status_code == 302, start.text
    location = start.headers["location"]
    assert location.startswith("https://as.example.com/authorize?")
    from urllib.parse import parse_qs, urlsplit

    params = parse_qs(urlsplit(location).query)
    assert params["client_id"] == ["https://gw.example.com/api/mcp/oauth/client-metadata.json"]
    assert params["redirect_uri"] == ["https://gw.example.com/api/mcp/oauth/callback"]
    assert params["code_challenge_method"] == ["S256"] and params["resource"] == ["https://mcp.vendor.example/mcp"]
    assert params["scope"] == ["docs:read"]
    state = params["state"][0]

    exchanged: dict[str, Any] = {}

    async def fake_exchange(oauth, client_secret, *, code, code_verifier, gateway_url, client=None):
        exchanged.update(code=code, verifier=code_verifier, gateway_url=gateway_url)
        return {"access_token": "at-SECRET", "refresh_token": "rt-SECRET", "expires_at": None, "scopes": "docs:read",
                "token_type": "Bearer", "id_token": _id_token({"email": "ada@example.com", "name": "Ada"})}

    async def fake_list(spec, client_factory=None):
        assert spec.headers["Authorization"] == "Bearer at-SECRET"
        return ([tool_info_from_upstream(_tool("search", readOnlyHint=True))], "2025-11-25", "Vendor")

    monkeypatch.setattr(oauth_api.oauth_mod, "exchange_code", fake_exchange)
    monkeypatch.setattr(api_common, "list_tools_via_sdk", fake_list)
    callback = h.client.get(f"{BASE}/oauth/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert callback.status_code in (302, 307), callback.text
    assert callback.headers["location"] == (
        f"https://app.example.com/settings/connectors?tab=access&connector={created['id']}&signin=ok"
    )
    assert exchanged["code"] == "abc" and exchanged["gateway_url"] == "https://gw.example.com" and exchanged["verifier"]

    detail = h.client.get(f"{BASE}/connectors/{created['id']}").json()
    assert detail["status"] == "connected" and detail["my_state"]["signed_in"] is True
    assert detail["my_state"]["signed_in_at"] and "SECRET" not in h.client.get(f"{BASE}/connectors/{created['id']}").text
    assert detail["my_state"]["account_label"] == "ada@example.com"
    assert detail["tool_count"] == 1

    # Replay is rejected; other members are not signed in.
    replay = h.client.get(f"{BASE}/oauth/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert replay.status_code == 400
    assert harness.as_user("user-b").client.get(f"{BASE}/connectors").json()["connectors"] == []

    signed_out = harness.as_user("user-a").client.post(f"{BASE}/connectors/{created['id']}/oauth/sign-out")
    assert signed_out.status_code == 200 and signed_out.json()["signed_in"] is False
    assert signed_out.json()["account_label"] is None
    assert h.client.get(f"{BASE}/connectors/{created['id']}").json()["status"] == "needs_sign_in"


def test_oauth_start_needs_registered_client_when_provider_has_none(harness: Harness, monkeypatch) -> None:
    async def manual_probe(url: str, **_kwargs) -> ProbeResult:
        result = await _oauth_probe(url)
        result.discovery.registration = "manual"
        result.discovery.metadata.pop("client_id_metadata_document_supported")
        return result

    monkeypatch.setattr(connectors_api, "probe_url", manual_probe)
    h = harness.as_user("user-a")
    created = _create(h, name="Vendor")
    assert h.client.get(f"{BASE}/connectors/{created['id']}/oauth/start", follow_redirects=False).status_code == 409
    with_client = _create(h, name="Vendor Two", oauth_client={"client_id": "pre-registered", "client_secret": "cs-SECRET"})
    assert "cs-SECRET" not in h.client.get(f"{BASE}/connectors/{with_client['id']}").text
    start = h.client.get(f"{BASE}/connectors/{with_client['id']}/oauth/start", follow_redirects=False)
    assert start.status_code == 302 and "client_id=pre-registered" in start.headers["location"]


def test_client_metadata_document_is_public(harness: Harness, monkeypatch) -> None:
    monkeypatch.setenv("SP_MCP_OAUTH_PUBLIC_URL", "https://gw.example.com")
    anonymous = TestClient(mcp_api.router and harness.client.app)
    response = anonymous.get(f"{BASE}/oauth/client-metadata.json")
    assert response.status_code == 200
    assert response.json()["redirect_uris"] == ["https://gw.example.com/api/mcp/oauth/callback"]
