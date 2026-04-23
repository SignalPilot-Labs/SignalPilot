"""Tests for sandbox session token hardening in sandbox_manager.py.

Covers:
- /vms endpoint truncates session tokens in response
- execute_handler rejects oversized session tokens (> 128 chars)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

# Add sp-sandbox root to path so imports resolve correctly.
_SANDBOX_ROOT = Path(__file__).parent.parent
if str(_SANDBOX_ROOT) not in sys.path:
    sys.path.insert(0, str(_SANDBOX_ROOT))

import sandbox_manager  # noqa: E402 — must follow sys.path manipulation


def _make_app() -> web.Application:
    return sandbox_manager.create_app()


@pytest.fixture()
def app() -> web.Application:
    return _make_app()


# ─── TestVmsTokenTruncation ───────────────────────────────────────────────────


class TestVmsTokenTruncation:
    """Tests that /vms endpoint truncates session tokens."""

    @pytest.mark.asyncio
    async def test_vms_response_truncates_token(self, app: web.Application):
        """Full session token must not appear in /vms response."""
        full_token = "supersecrettoken1234567890"
        vm_id = "vm-test-001"

        original_sessions = sandbox_manager.active_sessions
        sandbox_manager.active_sessions = {full_token: vm_id}

        try:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/vms")
                assert resp.status == 200
                data = await resp.json()
        finally:
            sandbox_manager.active_sessions = original_sessions

        vms = data["active_vms"]
        assert len(vms) == 1
        returned_token = vms[0]["session_token"]

        assert returned_token == "supersec..."
        assert full_token not in returned_token

    @pytest.mark.asyncio
    async def test_vms_truncation_format_is_eight_chars_plus_ellipsis(self, app: web.Application):
        """Token in /vms response must be exactly token[:8] + '...'."""
        token = "abcdefghijklmnopqrstuvwxyz"
        vm_id = "vm-test-002"

        original_sessions = sandbox_manager.active_sessions
        sandbox_manager.active_sessions = {token: vm_id}

        try:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/vms")
                data = await resp.json()
        finally:
            sandbox_manager.active_sessions = original_sessions

        returned_token = data["active_vms"][0]["session_token"]
        assert returned_token == "abcdefgh..."

    @pytest.mark.asyncio
    async def test_vms_empty_sessions_returns_empty_list(self, app: web.Application):
        """Empty active_sessions returns an empty list."""
        original_sessions = sandbox_manager.active_sessions
        sandbox_manager.active_sessions = {}

        try:
            async with TestClient(TestServer(app)) as client:
                resp = await client.get("/vms")
                data = await resp.json()
        finally:
            sandbox_manager.active_sessions = original_sessions

        assert data["active_vms"] == []


# ─── TestSessionTokenLengthValidation ────────────────────────────────────────


class TestSessionTokenLengthValidation:
    """Tests that oversized session tokens are rejected in /execute."""

    @pytest.mark.asyncio
    async def test_oversized_token_rejected_with_400(self, app: web.Application):
        """session_token longer than 128 chars must be rejected with 400."""
        oversized_token = "x" * 129

        async with TestClient(TestServer(app)) as client:
            resp = await client.post(
                "/execute",
                json={
                    "code": "print('hello')",
                    "session_token": oversized_token,
                },
            )
            assert resp.status == 400
            data = await resp.json()
            assert data["error"] == "Invalid session token"

    @pytest.mark.asyncio
    async def test_token_at_exact_limit_is_accepted(self, app: web.Application):
        """session_token exactly 128 chars is within limit and must not be rejected for length."""
        token_128 = "a" * 128

        mock_result = AsyncMock()
        mock_result.success = True
        mock_result.output = "hello"
        mock_result.error = None
        mock_result.vm_id = "vm-test-128"
        mock_result.execution_ms = 10.0

        with patch.object(sandbox_manager.executor, "execute", return_value=mock_result):
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/execute",
                    json={
                        "code": "print('hello')",
                        "session_token": token_128,
                    },
                )

        # Must not be rejected due to token length (may fail for other reasons
        # like gVisor not available, but not for token length)
        assert resp.status != 400 or (await resp.json()).get("error") != "Invalid session token"

    @pytest.mark.asyncio
    async def test_oversized_token_rejected_before_audit_logging(self, app: web.Application):
        """Oversized token rejection must happen before any audit logging."""
        oversized_token = "y" * 200

        with patch("sandbox_manager.audit.log_execution") as mock_audit:
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    "/execute",
                    json={
                        "code": "print('hello')",
                        "session_token": oversized_token,
                    },
                )

        assert resp.status == 400
        mock_audit.assert_not_called()
