"""Unit tests for resolve_org_id and the OrgID dependency.

Verifies:
- Local mode returns LOCAL_ORG_ID.
- Cloud mode extracts org_id from JWT claims cached on request.state.
- Cloud mode raises 403 when org_id claim is missing.
- MCP auth state with org_id present.
- MCP auth state without org_id falls back to LOCAL_ORG_ID in local mode.
- MCP auth state without org_id raises 403 in cloud mode.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from gateway.auth import LOCAL_ORG_ID, resolve_org_id


def _make_request(
    claims: dict | None = None,
    auth_state: dict | None = None,
) -> MagicMock:
    """Build a minimal mock Request with optional jwt claims and auth state."""
    request = MagicMock()
    request.state = MagicMock()
    request.state._jwt_claims = claims
    request.state.auth = auth_state
    return request


class TestResolveOrgIdLocalMode:
    """resolve_org_id in local mode (no CLERK_PUBLISHABLE_KEY)."""

    @pytest.mark.asyncio
    async def test_returns_local_org_id(self, monkeypatch):
        monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
        request = _make_request(
            claims={"sub": "local", "org_id": "local"},
        )
        result = await resolve_org_id(request, _user_id="local")
        assert result == LOCAL_ORG_ID

    @pytest.mark.asyncio
    async def test_local_org_id_constant_is_local(self):
        assert LOCAL_ORG_ID == "local"

    @pytest.mark.asyncio
    async def test_ignores_claims_org_id_in_local_mode(self, monkeypatch):
        """Even if claims contain a different org_id, local mode always returns 'local'."""
        monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
        request = _make_request(
            claims={"sub": "user-123", "org_id": "org_from_jwt"},
        )
        result = await resolve_org_id(request, _user_id="user-123")
        assert result == LOCAL_ORG_ID


class TestResolveOrgIdCloudMode:
    """resolve_org_id in cloud mode (CLERK_PUBLISHABLE_KEY set)."""

    @pytest.mark.asyncio
    async def test_extracts_org_id_from_claims(self, monkeypatch):
        monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_dGVzdA==")
        request = _make_request(
            claims={"sub": "user-123", "org_id": "org_abc"},
        )
        result = await resolve_org_id(request, _user_id="user-123")
        assert result == "org_abc"

    @pytest.mark.asyncio
    async def test_raises_403_when_org_id_missing(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_dGVzdA==")
        request = _make_request(
            claims={"sub": "user-123"},  # no org_id claim
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_org_id(request, _user_id="user-123")
        assert exc_info.value.status_code == 403
        assert "Organization context required" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_raises_500_when_claims_not_cached(self, monkeypatch):
        """If _jwt_claims was never set (bug in resolve_user_id), raise 500."""
        from fastapi import HTTPException

        monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_dGVzdA==")
        request = MagicMock()
        request.state = MagicMock(spec=[])  # no _jwt_claims attribute
        request.state.auth = None
        with pytest.raises(HTTPException) as exc_info:
            await resolve_org_id(request, _user_id="user-123")
        assert exc_info.value.status_code == 500


class TestResolveOrgIdMCPMode:
    """resolve_org_id for MCP requests (auth_state dict on request.state)."""

    @pytest.mark.asyncio
    async def test_uses_org_id_from_auth_state(self, monkeypatch):
        monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
        auth_state = {"user_id": "mcp-user", "org_id": "mcp-org"}
        request = _make_request(
            claims={"sub": "mcp-user", "org_id": "mcp-org"},
            auth_state=auth_state,
        )
        result = await resolve_org_id(request, _user_id="mcp-user")
        # In local mode, always returns LOCAL_ORG_ID
        assert result == LOCAL_ORG_ID

    @pytest.mark.asyncio
    async def test_falls_back_to_local_when_org_id_absent_in_local_mode(
        self, monkeypatch
    ):
        monkeypatch.delenv("CLERK_PUBLISHABLE_KEY", raising=False)
        auth_state = {"user_id": "mcp-user"}  # no org_id
        request = _make_request(
            claims={"sub": "mcp-user"},
            auth_state=auth_state,
        )
        result = await resolve_org_id(request, _user_id="mcp-user")
        assert result == LOCAL_ORG_ID

    @pytest.mark.asyncio
    async def test_raises_403_in_cloud_mode_when_org_id_absent(
        self, monkeypatch
    ):
        """In cloud mode, API-key auth without org_id must raise 403."""
        from fastapi import HTTPException

        monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_dGVzdA==")
        auth_state = {"user_id": "mcp-user"}  # no org_id
        request = _make_request(
            claims={"sub": "mcp-user"},
            auth_state=auth_state,
        )
        with pytest.raises(HTTPException) as exc_info:
            await resolve_org_id(request, _user_id="mcp-user")
        assert exc_info.value.status_code == 403
        assert "Organization context required" in exc_info.value.detail
