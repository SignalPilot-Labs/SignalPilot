"""Connectors domain rules: slugs (R9), SSRF guard (R8), tool defaults (R3), policy (R4), OAuth helpers (R6)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gateway.mcp_connectors import oauth as oauth_mod
from gateway.mcp_connectors import policy as policy_mod
from gateway.mcp_connectors import ssrf
from gateway.mcp_connectors.probe import parse_command, probe_command
from gateway.mcp_connectors.slugs import SlugCollisionError, allocate_slug, slugify
from gateway.mcp_connectors.tools import (
    allowed_tool_names,
    apply_tool_settings,
    default_controls,
    merge_inventory,
    public_tool_info,
    tool_info_from_upstream,
)
from gateway.mcp_connectors.upstream import UpstreamSpec, unwrap_http_error

# ── Slugs ────────────────────────────────────────────────────────────────────


def test_slugify_kebab_snake_and_bounds() -> None:
    assert slugify("GitHub Issues") == "github_issues"
    assert slugify("  Jira -- Cloud!! ") == "jira_cloud"
    assert len(slugify("x" * 80)) == 40
    with pytest.raises(ValueError):
        slugify("!")


def test_personal_slug_gets_mine_suffix_when_org_slug_exists() -> None:
    assert allocate_slug("GitHub", scope="personal", org_slugs={"github"}, own_slugs=set()) == "github_mine"
    assert allocate_slug("GitHub", scope="personal", org_slugs=set(), own_slugs=set()) == "github"
    with pytest.raises(SlugCollisionError):
        allocate_slug("GitHub", scope="personal", org_slugs={"github"}, own_slugs={"github_mine"})
    with pytest.raises(SlugCollisionError):
        allocate_slug("GitHub", scope="org", org_slugs={"github"}, own_slugs=set())


# ── SSRF ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ip",
    ["10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "127.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:10.0.0.1"],
)
def test_blocked_ip_ranges(ip: str) -> None:
    assert ssrf.is_blocked_ip(ip)


def test_public_ips_are_not_blocked() -> None:
    assert not ssrf.is_blocked_ip("93.184.216.34")
    assert not ssrf.is_blocked_ip("2606:2800:220:1:248:1893:25c8:1946")


def test_url_syntax_rejects_non_https_and_credentials(monkeypatch) -> None:
    monkeypatch.setattr(ssrf, "is_cloud_mode", lambda: False)
    with pytest.raises(ssrf.UnsafeUrlError):
        ssrf.validate_url_syntax("ftp://example.com/mcp")
    with pytest.raises(ssrf.UnsafeUrlError):
        ssrf.validate_url_syntax("http://example.com/mcp")
    with pytest.raises(ssrf.UnsafeUrlError):
        ssrf.validate_url_syntax("https://user:pw@example.com/mcp")
    assert ssrf.validate_url_syntax("http://localhost:3001/mcp#frag") == "http://localhost:3001/mcp"


def test_http_localhost_rejected_in_cloud_mode(monkeypatch) -> None:
    monkeypatch.setattr(ssrf, "is_cloud_mode", lambda: True)
    with pytest.raises(ssrf.UnsafeUrlError):
        ssrf.validate_url_syntax("http://localhost:3001/mcp")
    with pytest.raises(ssrf.UnsafeUrlError):
        ssrf.validate_url_syntax("http://127.0.0.1/mcp")


@pytest.mark.asyncio
async def test_validate_remote_url_rejects_private_targets(monkeypatch) -> None:
    monkeypatch.setattr(ssrf, "is_cloud_mode", lambda: True)
    for url in ("https://169.254.169.254/latest/meta-data/", "https://10.0.0.8/mcp", "https://[::1]/mcp"):
        with pytest.raises(ssrf.UnsafeUrlError):
            await ssrf.validate_remote_url(url)


@pytest.mark.asyncio
async def test_validate_remote_url_rejects_hosts_resolving_to_private(monkeypatch) -> None:
    monkeypatch.setattr(ssrf, "is_cloud_mode", lambda: True)

    async def fake_getaddrinfo(host, port, **_kwargs):
        return [(None, None, None, None, ("192.168.7.7", port))]

    import asyncio

    monkeypatch.setattr(asyncio.get_event_loop_policy().get_event_loop(), "getaddrinfo", fake_getaddrinfo, raising=False)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ssrf.UnsafeUrlError):
        await ssrf.validate_remote_url("https://internal.example.test/mcp")


@pytest.mark.asyncio
async def test_validate_remote_url_accepts_public_host(monkeypatch) -> None:
    import asyncio

    async def fake_getaddrinfo(host, port, **_kwargs):
        return [(None, None, None, None, ("93.184.216.34", port))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    assert await ssrf.validate_remote_url("https://mcp.example.com/mcp") == "https://mcp.example.com/mcp"


# ── Tools (R3) ───────────────────────────────────────────────────────────────


def _tool(name: str, **annotations):
    return SimpleNamespace(
        name=name,
        title=None,
        description=f"{name} description\x00 with control char",
        inputSchema={"type": "object"},
        annotations=SimpleNamespace(model_dump=lambda exclude_none=True: annotations, title=None),
    )


def test_default_controls_from_annotations() -> None:
    assert default_controls({"read_only_hint": True}) == (True, "auto")
    assert default_controls({"destructive_hint": True}) == (False, "off")
    assert default_controls({"read_only_hint": True, "destructive_hint": True}) == (False, "off")
    assert default_controls({}) == (False, "off")


def test_tool_info_strips_control_chars_and_seeds_defaults() -> None:
    info = tool_info_from_upstream(_tool("search", readOnlyHint=True))
    assert info["enabled"] is True and info["policy"] == "auto"
    assert "\x00" not in info["description"]
    assert info["annotations"] == {"read_only_hint": True}
    public = public_tool_info(info)
    assert "input_schema" not in public
    assert set(public) == {"name", "title", "description", "annotations", "enabled", "policy", "discovered_at", "is_new"}


def test_merge_inventory_new_tools_off_and_flagged() -> None:
    first = [tool_info_from_upstream(_tool("search", readOnlyHint=True))]
    merged, added, removed = merge_inventory([], first, first_connect=True)
    assert merged[0]["enabled"] is True and merged[0]["is_new"] is False and added == [] and removed == []

    later = [
        tool_info_from_upstream(_tool("search", readOnlyHint=True)),
        tool_info_from_upstream(_tool("read_only_new", readOnlyHint=True)),
    ]
    merged2, added2, removed2 = merge_inventory(merged, later, first_connect=False)
    by_name = {t["name"]: t for t in merged2}
    assert added2 == ["read_only_new"] and removed2 == []
    assert by_name["search"]["enabled"] is True
    # Even a read-only tool discovered later starts OFF (platform-lead #5).
    assert by_name["read_only_new"]["enabled"] is False and by_name["read_only_new"]["is_new"] is True

    merged3, _, removed3 = merge_inventory(merged2, [later[1]], first_connect=False)
    assert removed3 == ["search"] and [t["name"] for t in merged3] == ["read_only_new"]


def test_apply_settings_and_allowed_names_respect_member_and_run_origin() -> None:
    tools = [
        tool_info_from_upstream(_tool("search", readOnlyHint=True)),
        tool_info_from_upstream(_tool("delete", destructiveHint=True)),
    ]
    tools = apply_tool_settings(tools, {"delete": {"enabled": True, "policy": "ask"}})
    assert allowed_tool_names(tools) == ["search", "delete"]
    assert allowed_tool_names(tools, member_disabled=["search"]) == ["delete"]
    # Unattended runs only get auto tools.
    assert allowed_tool_names(tools, run_origin="improvement") == ["search"]
    assert allowed_tool_names(apply_tool_settings(tools, {"search": {"enabled": False}}), run_origin="improvement") == []


# ── Policy (R4) ──────────────────────────────────────────────────────────────


def test_host_allowed_globs() -> None:
    assert policy_mod.host_allowed("mcp.example.com", [])
    assert policy_mod.host_allowed("mcp.example.com", ["*.example.com"])
    assert not policy_mod.host_allowed("evil.test", ["*.example.com", "mcp.linear.app"])


def _connector(**overrides):
    base = {
        "enabled": True,
        "status": "connected",
        "scope": "personal",
        "url": "https://mcp.example.com/mcp",
        "auth": "none",
        "transport": "http",
        "env_json": [],
        "headers_enc": None,
        "tools_json": [{"name": "search", "enabled": True, "policy": "auto"}],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_evaluate_access_personal_policy_and_member_switch() -> None:
    connector = _connector()
    policy = SimpleNamespace(allow_personal=False, allowed_hosts_json=[])
    assert policy_mod.evaluate_access(connector, member=None, policy=policy).reason == "personal_not_allowed"
    policy = SimpleNamespace(allow_personal=True, allowed_hosts_json=["*.linear.app"])
    assert policy_mod.evaluate_access(connector, member=None, policy=policy).reason == "host_not_allowed"
    policy = SimpleNamespace(allow_personal=True, allowed_hosts_json=["*.example.com"])
    assert policy_mod.evaluate_access(connector, member=None, policy=policy).allowed_tools == ["search"]
    member = SimpleNamespace(enabled=False, disabled_tools_json=[], headers_enc=None, env_enc=None, oauth_tokens_enc=None)
    assert policy_mod.evaluate_access(connector, member=member, policy=policy).reason == "off_for_me"
    assert policy_mod.evaluate_access(_connector(enabled=False), member=None, policy=None).reason == "disabled"
    assert policy_mod.evaluate_access(_connector(auth="oauth"), member=None, policy=None).reason == "needs_sign_in"
    assert policy_mod.evaluate_access(_connector(auth="key"), member=None, policy=None).reason == "needs_key"


# ── OAuth helpers (R6) ───────────────────────────────────────────────────────


def test_pkce_and_www_authenticate_parsing() -> None:
    verifier, challenge = oauth_mod.make_pkce()
    assert 43 <= len(verifier) <= 128 and "=" not in challenge
    fields = oauth_mod.parse_www_authenticate(
        'Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource", scope="files:read"'
    )
    assert fields["resource_metadata"].endswith("oauth-protected-resource") and fields["scope"] == "files:read"


def test_cimd_document_and_authorize_url() -> None:
    doc = oauth_mod.cimd_document("https://gw.example.com/")
    assert doc["client_id"] == "https://gw.example.com/api/mcp/oauth/client-metadata.json"
    assert doc["redirect_uris"] == ["https://gw.example.com/api/mcp/oauth/callback"]
    assert doc["application_type"] == "web"
    oauth = {
        "client_id": doc["client_id"],
        "authorization_endpoint": "https://as.example.com/authorize?audience=x",
        "resource": "https://mcp.example.com/mcp",
        "scopes": "files:read",
    }
    url = oauth_mod.build_authorize_url(oauth, state="st", code_challenge="ch", gateway_url="https://gw.example.com")
    assert url.startswith("https://as.example.com/authorize?audience=x&")
    assert "code_challenge_method=S256" in url and "resource=https%3A%2F%2Fmcp.example.com%2Fmcp" in url
    assert "scope=files%3Aread" in url and "state=st" in url


def test_tokens_from_response_keeps_rotated_refresh_and_expiry() -> None:
    tokens = oauth_mod.tokens_from_response({"access_token": "a", "expires_in": 3600}, previous_refresh="r0")
    assert tokens["refresh_token"] == "r0" and tokens["expires_at"] is not None and tokens["id_token"] is None
    assert not oauth_mod.token_expiring(tokens)
    assert oauth_mod.token_expiring({"access_token": "a", "expires_at": 1.0})
    assert oauth_mod.canonical_resource("HTTPS://MCP.Example.com/mcp/") == "https://mcp.example.com/mcp"


def _id_token(claims) -> str:
    import base64
    import json

    segment = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"h.{segment}.s"


def test_account_label_comes_from_id_token_email_then_username_then_name() -> None:
    label = oauth_mod.account_label_from_tokens
    assert label({"id_token": _id_token({"email": "ada@example.com", "name": "Ada"})}) == "ada@example.com"
    assert label({"id_token": _id_token({"preferred_username": "ada", "name": "Ada"})}) == "ada"
    assert label({"id_token": _id_token({"name": "  Ada\x00 Lovelace "})}) == "Ada Lovelace"
    assert label({"id_token": _id_token({"sub": "opaque"})}) is None
    assert label({"id_token": _id_token(["not", "an", "object"])}) is None
    assert label({"id_token": "garbage"}) is None and label({"id_token": "a.!!!.c"}) is None
    assert label({"access_token": "a"}) is None and label(None) is None
    long_name = "x" * 500
    assert len(label({"id_token": _id_token({"name": long_name})}) or "") == 200
    # A token endpoint that returns an id_token carries it through unchanged.
    assert oauth_mod.tokens_from_response({"access_token": "a", "id_token": "h.p.s"})["id_token"] == "h.p.s"


def test_org_name_from_clerk_claims_prefers_names_over_slugs() -> None:
    from gateway.auth.user import org_name_from_claims

    assert org_name_from_claims(None) is None and org_name_from_claims({}) is None
    assert org_name_from_claims({"o": {"id": "org_1", "rol": "admin"}}) is None
    assert org_name_from_claims({"o": {"id": "org_1", "slg": "acme"}}) == "acme"
    assert org_name_from_claims({"o": {"id": "org_1", "slg": "acme", "nam": "Acme Inc"}}) == "Acme Inc"
    assert org_name_from_claims({"org_slug": "acme", "org_name": "  Acme Inc "}) == "Acme Inc"
    assert org_name_from_claims({"org_name": "", "org_slug": "acme"}) == "acme"
    assert org_name_from_claims({"o": "org_1"}) is None


def test_user_label_is_null_until_a_user_directory_exists() -> None:
    from gateway.store.mcp.tool_calls import user_label_for

    assert user_label_for("user_2abc") is None and user_label_for("local") is None and user_label_for(None) is None


def test_register_client_order_manual_then_cimd_then_ask(monkeypatch) -> None:
    import asyncio

    manual = {"client_id": "pre", "registration": "manual"}
    assert asyncio.run(oauth_mod.register_client(manual, gateway_url="https://gw"))[0]["client_id"] == "pre"
    cimd = {"client_id": None, "registration": "cimd"}
    assert asyncio.run(oauth_mod.register_client(cimd, gateway_url="https://gw"))[0]["client_id"].endswith(
        "/api/mcp/oauth/client-metadata.json"
    )
    with pytest.raises(oauth_mod.NeedsClientRegistration):
        asyncio.run(oauth_mod.register_client({"client_id": None, "registration": "manual"}, gateway_url="https://gw"))


# ── Probe (stdio) and upstream helpers ───────────────────────────────────────


def test_probe_command_blocks_docker_and_parses_args() -> None:
    assert parse_command("npx -y @modelcontextprotocol/server-everything") == (
        "npx",
        ["-y", "@modelcontextprotocol/server-everything"],
    )
    result = probe_command("docker run mcp/server")
    assert result.transport == "stdio" and result.error and "docker" in result.error
    ok = probe_command("uvx", ["mcp-server-fetch"])
    assert ok.error is None and ok.auth == "none" and ok.tools is None


def test_unwrap_http_error_finds_nested_status_error() -> None:
    import httpx

    response = httpx.Response(401, headers={"WWW-Authenticate": 'Bearer resource_metadata="https://x/.well-known"'})
    error = httpx.HTTPStatusError("401", request=httpx.Request("POST", "https://x"), response=response)
    grouped = ExceptionGroup("g", [RuntimeError("other"), ExceptionGroup("inner", [error])])
    assert unwrap_http_error(grouped) is error
    assert unwrap_http_error(RuntimeError("no")) is None
    assert UpstreamSpec("https://x", "http", {"A": "1"}).fingerprint() != UpstreamSpec("https://x", "http", {}).fingerprint()
