"""Tests for the Clerk OAuth resource-server path on /mcp.

Covers: discovery documents, the WWW-Authenticate challenge, JWT verification
(issuer / audience / expiry / org), role→scope mapping, and the middleware
branch that runs the MCP app as the OAuth principal.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.auth import mcp_oauth
from gateway.auth.mcp_api_key import MCPAuthMiddleware

FRONTEND_DOMAIN = "endless-fly-19.clerk.accounts.dev"
ISSUER = f"https://{FRONTEND_DOMAIN}"
PUBLIC_URL = "https://gw.example.test"
RESOURCE = f"{PUBLIC_URL}/mcp"


def _publishable_key() -> str:
    return "pk_test_" + base64.b64encode(f"{FRONTEND_DOMAIN}$".encode()).decode().rstrip("=")


_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_PEM = _PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


def _mint(**overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "user_123",
        "aud": RESOURCE,
        "exp": now + 3600,
        "iat": now,
        "azp": "client_abc",
        "scope": "openid profile email user:org:read",
        "org_id": "org_456",
    }
    for key, value in overrides.items():
        if value is None:
            claims.pop(key, None)
        else:
            claims[key] = value
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", _publishable_key())
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_dummy")
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", "unit-test-session-secret-unit-test-session-secret")
    monkeypatch.setenv("SP_PUBLIC_GATEWAY_URL", PUBLIC_URL)
    monkeypatch.delenv("SP_MCP_OAUTH_RESOURCE_URL", raising=False)
    monkeypatch.delenv("SP_MCP_OAUTH_DISABLED", raising=False)
    from gateway.config import get_mcp_settings
    from gateway.config.gateway import get_gateway_settings

    get_mcp_settings.cache_clear()
    get_gateway_settings.cache_clear()
    mcp_oauth._membership_cache.clear()
    mcp_oauth._introspection_cache.clear()

    signing_key = MagicMock()
    signing_key.key = _PUBLIC_PEM
    jwks_client = MagicMock()
    jwks_client.get_signing_key_from_jwt.return_value = signing_key
    with patch("gateway.auth.user._get_jwks_client", return_value=jwks_client):
        yield
    get_mcp_settings.cache_clear()
    get_gateway_settings.cache_clear()


def _membership_response(role: str = "org:member", user_id: str = "user_123") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": [{"role": role, "public_user_data": {"user_id": user_id}}]}
    return resp


def _patch_clerk_get(resp: MagicMock):
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return patch("gateway.auth.mcp_oauth.httpx.AsyncClient", return_value=client)


# ─── Configuration / discovery ───────────────────────────────────────────────


class TestDiscovery:
    def test_enabled_only_in_cloud_mode_with_clerk(self, oauth_env, monkeypatch):
        assert mcp_oauth.oauth_enabled() is True
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        assert mcp_oauth.oauth_enabled() is False

    def test_disabled_flag_turns_oauth_off(self, oauth_env, monkeypatch):
        from gateway.config import get_mcp_settings

        monkeypatch.setenv("SP_MCP_OAUTH_DISABLED", "true")
        get_mcp_settings.cache_clear()
        assert mcp_oauth.oauth_enabled() is False

    def test_resource_and_metadata_urls_follow_public_gateway_url(self, oauth_env):
        assert mcp_oauth.resource_url() == RESOURCE
        assert mcp_oauth.resource_metadata_url() == f"{PUBLIC_URL}/.well-known/oauth-protected-resource/mcp"

    def test_resource_url_override(self, oauth_env, monkeypatch):
        from gateway.config import get_mcp_settings

        monkeypatch.setenv("SP_MCP_OAUTH_RESOURCE_URL", "https://mcp.other.test/mcp/")
        get_mcp_settings.cache_clear()
        assert mcp_oauth.resource_url() == "https://mcp.other.test/mcp"

    def test_protected_resource_metadata_points_at_clerk(self, oauth_env):
        doc = mcp_oauth.protected_resource_metadata()
        assert doc["resource"] == RESOURCE
        assert doc["authorization_servers"] == [ISSUER]
        assert "user:org:read" in doc["scopes_supported"]
        assert doc["bearer_methods_supported"] == ["header"]

    def test_www_authenticate_has_resource_metadata_and_scope(self, oauth_env):
        header = mcp_oauth.www_authenticate("invalid_token", 'Bad "token"')
        assert header.startswith("Bearer ")
        assert 'error="invalid_token"' in header
        assert f'resource_metadata="{PUBLIC_URL}/.well-known/oauth-protected-resource/mcp"' in header
        assert 'scope="openid profile email user:org:read"' in header
        assert '"token"' not in header  # quotes inside the description are neutralised

    def test_well_known_routes(self, oauth_env):
        from gateway.api.oauth_metadata import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        for path in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert resp.json()["resource"] == RESOURCE
            assert resp.headers["access-control-allow-origin"] == "*"

        as_doc = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/oauth/authorize"}
        with patch(
            "gateway.api.oauth_metadata.fetch_authorization_server_metadata",
            new=AsyncMock(return_value=as_doc),
        ):
            resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        assert resp.json()["issuer"] == ISSUER

        assert client.options("/.well-known/oauth-protected-resource").status_code == 204

    def test_well_known_routes_404_when_disabled(self, oauth_env, monkeypatch):
        from gateway.api.oauth_metadata import router

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        app = FastAPI()
        app.include_router(router)
        assert TestClient(app).get("/.well-known/oauth-protected-resource").status_code == 404


# ─── Token classification ───────────────────────────────────────────────────


class TestCandidate:
    def test_clerk_jwt_is_candidate(self, oauth_env):
        assert mcp_oauth.is_oauth_candidate(_mint()) is True

    def test_notebook_session_jwt_is_not_candidate(self, oauth_env):
        token = jwt.encode({"iss": "signalpilot-notebook-session", "sub": "u"}, "secret", algorithm="HS256")
        assert mcp_oauth.is_oauth_candidate(token) is False

    def test_opaque_token_is_candidate(self, oauth_env):
        assert mcp_oauth.is_oauth_candidate("oat_abcdef0123456789") is True

    def test_garbage_jwt_is_not_candidate(self, oauth_env):
        assert mcp_oauth.is_oauth_candidate("a.b.c") is False


# ─── Verification ────────────────────────────────────────────────────────────


class TestVerify:
    @pytest.mark.asyncio
    async def test_valid_member_token(self, oauth_env):
        with _patch_clerk_get(_membership_response("org:member")):
            principal = await mcp_oauth.verify_oauth_token(_mint())
        assert principal.user_id == "user_123"
        assert principal.org_id == "org_456"
        assert principal.org_role == "org:member"
        assert principal.client_id == "client_abc"
        assert "admin" not in principal.scopes
        assert {"read", "query", "execute", "write"} <= set(principal.scopes)

    @pytest.mark.asyncio
    async def test_admin_role_gets_admin_scope(self, oauth_env):
        with _patch_clerk_get(_membership_response("org:admin")):
            principal = await mcp_oauth.verify_oauth_token(_mint())
        assert "admin" in principal.scopes

    @pytest.mark.asyncio
    async def test_membership_is_cached(self, oauth_env):
        patcher = _patch_clerk_get(_membership_response())
        with patcher as client_cls:
            await mcp_oauth.verify_oauth_token(_mint())
            await mcp_oauth.verify_oauth_token(_mint())
        assert client_cls.return_value.get.await_count == 1

    @pytest.mark.asyncio
    async def test_wrong_audience_rejected(self, oauth_env):
        with pytest.raises(mcp_oauth.OAuthTokenError) as exc:
            await mcp_oauth.verify_oauth_token(_mint(aud="https://evil.test/mcp"))
        assert exc.value.status == 401
        assert exc.value.error == "invalid_token"

    @pytest.mark.asyncio
    async def test_audience_list_and_trailing_slash_accepted(self, oauth_env):
        with _patch_clerk_get(_membership_response()):
            principal = await mcp_oauth.verify_oauth_token(_mint(aud=["other", RESOURCE + "/"]))
        assert principal.org_id == "org_456"

    @pytest.mark.asyncio
    async def test_missing_audience_rejected_by_default(self, oauth_env):
        with pytest.raises(mcp_oauth.OAuthTokenError):
            await mcp_oauth.verify_oauth_token(_mint(aud=None))

    @pytest.mark.asyncio
    async def test_missing_audience_allowed_when_configured(self, oauth_env, monkeypatch):
        from gateway.config import get_mcp_settings

        monkeypatch.setenv("SP_MCP_OAUTH_REQUIRE_AUDIENCE", "false")
        get_mcp_settings.cache_clear()
        with _patch_clerk_get(_membership_response()):
            principal = await mcp_oauth.verify_oauth_token(_mint(aud=None))
        assert principal.user_id == "user_123"

    @pytest.mark.asyncio
    async def test_wrong_issuer_rejected(self, oauth_env):
        with pytest.raises(mcp_oauth.OAuthTokenError):
            await mcp_oauth.verify_oauth_token(_mint(iss="https://other.clerk.accounts.dev"))

    @pytest.mark.asyncio
    async def test_expired_rejected(self, oauth_env):
        with pytest.raises(mcp_oauth.OAuthTokenError) as exc:
            await mcp_oauth.verify_oauth_token(_mint(exp=int(time.time()) - 600))
        assert "expired" in exc.value.description

    @pytest.mark.asyncio
    async def test_missing_org_is_insufficient_scope_403(self, oauth_env):
        with pytest.raises(mcp_oauth.OAuthTokenError) as exc:
            await mcp_oauth.verify_oauth_token(_mint(org_id=None))
        assert exc.value.status == 403
        assert exc.value.error == "insufficient_scope"
        assert exc.value.scope == "user:org:read"

    @pytest.mark.asyncio
    async def test_prod_short_org_claim_supported(self, oauth_env):
        with _patch_clerk_get(_membership_response()):
            principal = await mcp_oauth.verify_oauth_token(_mint(org_id=None, o={"id": "org_456", "rol": "admin"}))
        assert principal.org_id == "org_456"

    @pytest.mark.asyncio
    async def test_non_member_rejected(self, oauth_env):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": []}
        with _patch_clerk_get(resp), pytest.raises(mcp_oauth.OAuthTokenError) as exc:
            await mcp_oauth.verify_oauth_token(_mint())
        assert exc.value.status == 403

    @pytest.mark.asyncio
    async def test_hs256_token_rejected(self, oauth_env):
        token = jwt.encode(
            {"iss": ISSUER, "sub": "u", "aud": RESOURCE, "exp": int(time.time()) + 60, "iat": int(time.time())},
            "secret",
            algorithm="HS256",
        )
        with pytest.raises(mcp_oauth.OAuthTokenError):
            await mcp_oauth.verify_oauth_token(token)


# ─── Middleware integration ─────────────────────────────────────────────────


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {"type": "http", "method": "POST", "path": "/mcp", "headers": headers or []}


async def _run(middleware: MCPAuthMiddleware, scope: dict) -> dict:
    events: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event: dict):
        events.append(event)

    await middleware(scope, receive, send)
    start = next(e for e in events if e["type"] == "http.response.start")
    body = next((e for e in events if e["type"] == "http.response.body"), None)
    headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    return {
        "status": start["status"],
        "headers": headers,
        "body": json.loads(body["body"]) if body and body.get("body") else None,
    }


class TestMiddleware:
    @pytest.mark.asyncio
    async def test_oauth_token_runs_app_as_principal(self, oauth_env):
        captured: dict = {}

        async def app(scope, receive, send):
            from gateway.mcp import context as ctx

            captured["auth"] = scope["state"]["auth"]
            captured["org"] = ctx.mcp_org_id_var.get()
            captured["scopes"] = ctx.mcp_scopes_var.get()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}", "more_body": False})

        with _patch_clerk_get(_membership_response("org:admin")):
            result = await _run(MCPAuthMiddleware(app), _scope([(b"authorization", f"Bearer {_mint()}".encode())]))

        assert result["status"] == 200
        assert captured["auth"]["auth_method"] == "oauth"
        assert captured["auth"]["user_id"] == "user_123"
        assert captured["org"] == "org_456"
        assert "admin" in captured["scopes"]

    @pytest.mark.asyncio
    async def test_bad_oauth_token_gets_challenge(self, oauth_env):
        async def app(scope, receive, send):
            pytest.fail("must not reach the MCP app")

        token = _mint(aud="https://evil.test/mcp")
        result = await _run(MCPAuthMiddleware(app), _scope([(b"authorization", f"Bearer {token}".encode())]))
        assert result["status"] == 401
        assert "resource_metadata=" in result["headers"]["www-authenticate"]
        assert result["body"]["error"] == "invalid_token"

    @pytest.mark.asyncio
    async def test_missing_org_gets_403_step_up(self, oauth_env):
        async def app(scope, receive, send):
            pytest.fail("must not reach the MCP app")

        token = _mint(org_id=None)
        result = await _run(MCPAuthMiddleware(app), _scope([(b"authorization", f"Bearer {token}".encode())]))
        assert result["status"] == 403
        assert 'error="insufficient_scope"' in result["headers"]["www-authenticate"]
        assert 'scope="user:org:read"' in result["headers"]["www-authenticate"]

    @pytest.mark.asyncio
    async def test_no_credential_401_carries_challenge(self, oauth_env):
        """The very first unauthenticated POST is how clients discover OAuth."""

        async def app(scope, receive, send):
            pytest.fail("must not reach the MCP app")

        store = MagicMock()
        store.list_api_keys = AsyncMock(return_value=[MagicMock()])
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        factory = MagicMock(return_value=session)
        with (
            patch("gateway.db.engine.get_session_factory", return_value=factory),
            patch("gateway.store.Store", return_value=store),
        ):
            result = await _run(MCPAuthMiddleware(app), _scope())
        assert result["status"] == 401
        www = result["headers"]["www-authenticate"]
        assert www.startswith("Bearer ")
        assert f'resource_metadata="{PUBLIC_URL}/.well-known/oauth-protected-resource/mcp"' in www

    @pytest.mark.asyncio
    async def test_notebook_jwt_still_takes_notebook_path(self, oauth_env):
        async def app(scope, receive, send):
            pytest.fail("must not reach the MCP app")

        token = jwt.encode({"iss": "signalpilot-notebook-session", "sub": "u"}, "secret", algorithm="HS256")
        result = await _run(MCPAuthMiddleware(app), _scope([(b"authorization", f"Bearer {token}".encode())]))
        assert result["status"] == 401
        assert result["body"]["detail"] == "Invalid notebook session token."

    @pytest.mark.asyncio
    async def test_local_mode_ignores_oauth(self, oauth_env, monkeypatch):
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")

        async def app(scope, receive, send):
            pytest.fail("must not reach the MCP app")

        result = await _run(MCPAuthMiddleware(app), _scope([(b"authorization", f"Bearer {_mint()}".encode())]))
        # Falls through to the notebook-session verifier, no OAuth challenge.
        assert result["status"] == 401
        assert "www-authenticate" not in result["headers"]
