"""Tests for API key scope enforcement, expiry, user_id propagation, and JWT error redaction."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.models import ApiKeyCreate, ApiKeyRecord, VALID_API_KEY_SCOPES
from gateway.scope_guard import require_scopes


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_request(auth: dict[str, Any] | None) -> MagicMock:
    """Build a mock FastAPI Request with request.state.auth set."""
    request = MagicMock()
    if auth is None:
        # Simulate no auth attribute set (JWT/Clerk path)
        del request.state.auth
        type(request.state).__getattr__ = lambda self, name: (_ for _ in ()).throw(AttributeError(name))
        request.state = MagicMock(spec=[])  # no 'auth' attribute
    else:
        request.state.auth = auth
    return request


def _make_api_key_request(scopes: list[str]) -> MagicMock:
    """Build a mock request with api_key auth."""
    request = MagicMock()
    request.state.auth = {
        "auth_method": "api_key",
        "user_id": "user_abc",
        "scopes": scopes,
    }
    return request


def _make_local_key_request() -> MagicMock:
    """Build a mock request with local_key auth."""
    request = MagicMock()
    request.state.auth = {"auth_method": "local_key", "user_id": "local"}
    return request


def _make_no_auth_request() -> MagicMock:
    """Build a mock request with no auth (JWT/Clerk path)."""
    request = MagicMock()
    # Remove auth attribute entirely to simulate Clerk JWT path
    request.state = MagicMock(spec=[])
    return request


# ─── TestScopeGuardRequireScopes ─────────────────────────────────────────────


class TestScopeGuardRequireScopes:
    """Unit tests for require_scopes() function."""

    def test_no_auth_attribute_grants_all_scopes(self):
        """JWT/Clerk users have no auth dict — all scopes granted."""
        request = _make_no_auth_request()
        # Should not raise
        require_scopes(request, "admin", "write", "execute")

    def test_local_key_bypasses_scope_check(self):
        """Local dev key bypasses all scope checks regardless of required scopes."""
        request = _make_local_key_request()
        # Should not raise even with no scopes on the key
        require_scopes(request, "admin", "execute", "write")

    def test_api_key_with_required_scope_passes(self):
        """API key with the required scope should pass without exception."""
        request = _make_api_key_request(scopes=["read", "query"])
        # Should not raise
        require_scopes(request, "query")

    def test_api_key_with_multiple_required_scopes_passes(self):
        """API key must have ALL required scopes."""
        request = _make_api_key_request(scopes=["read", "query", "write"])
        require_scopes(request, "read", "write")  # should not raise

    def test_api_key_missing_required_scope_raises_403(self):
        """API key without the required scope must get 403."""
        from fastapi import HTTPException

        request = _make_api_key_request(scopes=["read"])
        with pytest.raises(HTTPException) as exc_info:
            require_scopes(request, "query")
        assert exc_info.value.status_code == 403
        assert "Insufficient scope" in exc_info.value.detail

    def test_api_key_missing_one_of_multiple_scopes_raises_403(self):
        """If any required scope is missing, 403 is raised (flat model — no hierarchy)."""
        from fastapi import HTTPException

        request = _make_api_key_request(scopes=["read", "query"])
        with pytest.raises(HTTPException) as exc_info:
            require_scopes(request, "read", "execute")
        assert exc_info.value.status_code == 403

    def test_admin_scope_does_not_imply_write(self):
        """Scope model is flat — admin does not grant write."""
        from fastapi import HTTPException

        request = _make_api_key_request(scopes=["admin"])
        with pytest.raises(HTTPException):
            require_scopes(request, "write")

    def test_no_required_scopes_always_passes(self):
        """Requiring no scopes always passes regardless of key scopes."""
        request = _make_api_key_request(scopes=[])
        require_scopes(request)  # should not raise

    def test_auth_none_value_grants_all_scopes(self):
        """If request.state.auth is explicitly None, treat as JWT path."""
        request = MagicMock()
        request.state.auth = None
        require_scopes(request, "admin")  # should not raise


# ─── TestScopeAllowlistValidation ────────────────────────────────────────────


class TestScopeAllowlistValidation:
    """Tests for ApiKeyCreate scope allowlist validation."""

    def test_valid_scopes_accepted(self):
        for scope in VALID_API_KEY_SCOPES:
            obj = ApiKeyCreate(name="test", scopes=[scope])
            assert scope in obj.scopes

    def test_all_valid_scopes_accepted_together(self):
        obj = ApiKeyCreate(name="test", scopes=list(VALID_API_KEY_SCOPES))
        assert set(obj.scopes) == VALID_API_KEY_SCOPES

    def test_invalid_scope_raises_422(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            ApiKeyCreate(name="test", scopes=["god_mode"])
        assert "Invalid scope" in str(exc_info.value)

    def test_multiple_invalid_scopes_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ApiKeyCreate(name="test", scopes=["admin", "superuser", "root"])

    def test_empty_scopes_list_accepted(self):
        obj = ApiKeyCreate(name="test", scopes=[])
        assert obj.scopes == []

    def test_default_scopes_are_valid(self):
        obj = ApiKeyCreate(name="test")
        for scope in obj.scopes:
            assert scope in VALID_API_KEY_SCOPES


# ─── TestValidApiKeyScopes ────────────────────────────────────────────────────


class TestValidApiKeyScopes:
    """Tests for VALID_API_KEY_SCOPES constant."""

    def test_contains_expected_scopes(self):
        assert "read" in VALID_API_KEY_SCOPES
        assert "query" in VALID_API_KEY_SCOPES
        assert "execute" in VALID_API_KEY_SCOPES
        assert "write" in VALID_API_KEY_SCOPES
        assert "admin" in VALID_API_KEY_SCOPES

    def test_is_frozenset(self):
        assert isinstance(VALID_API_KEY_SCOPES, frozenset)


# ─── TestApiKeyExpiryValidation ───────────────────────────────────────────────


class TestApiKeyExpiryValidation:
    """Tests for expires_at validation in validate_stored_api_key."""

    @pytest.mark.asyncio
    async def test_expired_key_returns_none(self):
        """A key with expires_at in the past must return None."""
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        mock_row = MagicMock()
        mock_row.key_hash = hashlib.sha256(b"sp_testkey").hexdigest()
        mock_row.expires_at = past
        mock_row.id = str(uuid.uuid4())
        mock_row.name = "test"
        mock_row.prefix = "sp_test"
        mock_row.scopes = ["read"]
        mock_row.created_at = datetime.now(timezone.utc).isoformat()
        mock_row.last_used_at = None
        mock_row.user_id = "user_abc"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        from gateway.store import Store

        store = Store(mock_session)
        result = await store.validate_stored_api_key("sp_testkey")
        assert result is None

    @pytest.mark.asyncio
    async def test_valid_unexpired_key_returns_record(self):
        """A key with expires_at in the future must be returned."""
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        mock_row = MagicMock()
        raw_key = "sp_testkey_valid"
        mock_row.key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        mock_row.expires_at = future
        mock_row.id = str(uuid.uuid4())
        mock_row.name = "test"
        mock_row.prefix = "sp_test"
        mock_row.scopes = ["read", "query"]
        mock_row.created_at = datetime.now(timezone.utc).isoformat()
        mock_row.last_used_at = None
        mock_row.user_id = "user_abc"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        from gateway.store import Store

        store = Store(mock_session)
        result = await store.validate_stored_api_key(raw_key)
        assert result is not None
        assert result.scopes == ["read", "query"]

    @pytest.mark.asyncio
    async def test_no_expiry_key_always_valid(self):
        """A key with expires_at=None never expires."""
        mock_row = MagicMock()
        raw_key = "sp_no_expiry"
        mock_row.key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        mock_row.expires_at = None
        mock_row.id = str(uuid.uuid4())
        mock_row.name = "test"
        mock_row.prefix = "sp_no_"
        mock_row.scopes = ["read"]
        mock_row.created_at = datetime.now(timezone.utc).isoformat()
        mock_row.last_used_at = None
        mock_row.user_id = "user_xyz"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        from gateway.store import Store

        store = Store(mock_session)
        result = await store.validate_stored_api_key(raw_key)
        assert result is not None


# ─── TestUserIdPropagation ───────────────────────────────────────────────────


class TestUserIdPropagation:
    """Tests that user_id flows correctly from DB row through ApiKeyRecord."""

    @pytest.mark.asyncio
    async def test_validate_stored_api_key_propagates_user_id(self):
        """validate_stored_api_key must return the user_id from the DB row."""
        raw_key = "sp_propagate_user_id"
        mock_row = MagicMock()
        mock_row.key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        mock_row.expires_at = None
        mock_row.id = "key-id-123"
        mock_row.name = "my-key"
        mock_row.prefix = "sp_prop"
        mock_row.scopes = ["read"]
        mock_row.created_at = datetime.now(timezone.utc).isoformat()
        mock_row.last_used_at = None
        mock_row.user_id = "real_user_456"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        from gateway.store import Store

        store = Store(mock_session)
        record = await store.validate_stored_api_key(raw_key)
        assert record is not None
        assert record.user_id == "real_user_456"
        assert record.user_id != "local"

    def test_api_key_record_has_user_id_field(self):
        """ApiKeyRecord must have a user_id field."""
        record = ApiKeyRecord(
            id="1",
            name="test",
            prefix="sp_test",
            key_hash="abc",
            scopes=["read"],
            created_at="2026-01-01T00:00:00+00:00",
            user_id="specific_user",
        )
        assert record.user_id == "specific_user"


# ─── TestJwtErrorRedaction ───────────────────────────────────────────────────


class TestJwtErrorRedaction:
    """Tests that JWT error responses do not leak PyJWT exception details."""

    @pytest.mark.asyncio
    async def test_invalid_token_response_is_generic(self):
        """resolve_user_id must return a generic message, not f'Invalid token: {e}'."""
        import jwt as pyjwt

        from gateway.auth import resolve_user_id

        # Simulate cloud mode being active
        with patch("gateway.auth._is_cloud_mode", return_value=True):
            mock_client = MagicMock()
            mock_client.get_signing_key_from_jwt.side_effect = pyjwt.InvalidTokenError(
                "signature verification failed: algorithm=RS256, kid=abc123"
            )

            with patch("gateway.auth._get_jwks_client", return_value=mock_client):
                request = MagicMock()
                request.headers.get.return_value = "Bearer eyJfake.jwt.token"
                request.cookies.get.return_value = None
                request.state = MagicMock(spec=[])  # no auth attribute

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await resolve_user_id(request)

                detail = exc_info.value.detail
                # Must NOT contain raw exception details
                assert "algorithm" not in detail
                assert "RS256" not in detail
                assert "kid" not in detail
                assert "signature" not in detail
                # Must be the generic message
                assert detail == "Invalid authentication token"

    @pytest.mark.asyncio
    async def test_expired_token_response_is_specific_but_safe(self):
        """ExpiredSignatureError returns 'Token expired' — no library internals."""
        import jwt as pyjwt

        from gateway.auth import resolve_user_id

        with patch("gateway.auth._is_cloud_mode", return_value=True):
            mock_client = MagicMock()
            mock_client.get_signing_key_from_jwt.side_effect = pyjwt.ExpiredSignatureError(
                "Signature has expired."
            )

            with patch("gateway.auth._get_jwks_client", return_value=mock_client):
                request = MagicMock()
                request.headers.get.return_value = "Bearer eyJfake.expired.token"
                request.cookies.get.return_value = None
                request.state = MagicMock(spec=[])

                from fastapi import HTTPException

                with pytest.raises(HTTPException) as exc_info:
                    await resolve_user_id(request)

                assert exc_info.value.status_code == 401
                assert exc_info.value.detail == "Token expired"


# ─── TestApiKeyCreateExpiresAt ────────────────────────────────────────────────


class TestApiKeyCreateExpiresAt:
    """Tests for expires_at field on ApiKeyCreate."""

    def test_expires_at_defaults_to_none(self):
        obj = ApiKeyCreate(name="test", scopes=["read"])
        assert obj.expires_at is None

    def test_expires_at_can_be_set(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        obj = ApiKeyCreate(name="test", scopes=["read"], expires_at=future)
        assert obj.expires_at == future

    def test_api_key_record_has_expires_at_field(self):
        record = ApiKeyRecord(
            id="1",
            name="test",
            prefix="sp_test",
            key_hash="abc",
            scopes=["read"],
            created_at="2026-01-01T00:00:00+00:00",
            expires_at="2026-12-31T00:00:00+00:00",
        )
        assert record.expires_at == "2026-12-31T00:00:00+00:00"
