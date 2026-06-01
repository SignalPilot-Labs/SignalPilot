"""Tests for anthropic_key_preview — verifies trailing chars are never included.

Covers R2 L-3: log capture of response body must not reveal the last-4 chars
of the stored API key.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet


class TestMaskPreviewHelper:
    """Unit tests for the _mask_preview module helper."""

    def test_long_key_returns_prefix_and_ellipsis(self) -> None:
        from gateway.api.user_secrets import _mask_preview

        result = _mask_preview("sk-ant-api03-ABCDEFGHIJKLMNOP-XYZ9")
        assert result == "sk-ant-a..."

    def test_long_key_does_not_contain_suffix(self) -> None:
        from gateway.api.user_secrets import _mask_preview

        result = _mask_preview("sk-ant-api03-ABCDEFGHIJKLMNOP-XYZ9")
        assert "XYZ9" not in result

    def test_exactly_8_chars_returns_prefix_and_ellipsis(self) -> None:
        from gateway.api.user_secrets import _mask_preview

        result = _mask_preview("12345678")
        assert result == "12345678..."

    def test_short_key_below_8_returns_masked(self) -> None:
        from gateway.api.user_secrets import _mask_preview

        result = _mask_preview("short")
        assert result == "****"

    def test_empty_key_returns_masked(self) -> None:
        from gateway.api.user_secrets import _mask_preview

        result = _mask_preview("")
        assert result == "****"


class TestUserSecretsPreviewRoutes:
    """Integration tests: GET and PUT routes must not expose key suffix in preview."""

    def _make_client(self, monkeypatch, tmp_path, plaintext_secret: str):
        """Return (client, api_key, commit_mock) with a single pre-stored secret row."""
        encryption_key = Fernet.generate_key()
        monkeypatch.setenv("SP_ENCRYPTION_KEY", encryption_key.decode())
        monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        import gateway.store.crypto as crypto
        monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)

        from gateway.store.crypto import _encrypt
        ciphertext = _encrypt(plaintext_secret)

        row = MagicMock()
        row.org_id = "local"
        row.user_id = "local"
        row.anthropic_api_key_enc = ciphertext
        row.updated_at = time.time()

        commit_mock = AsyncMock()

        async def _mock_db_session():
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = row
            session.execute = AsyncMock(return_value=result)
            session.commit = commit_mock
            yield session

        from gateway.db.engine import get_db
        from gateway.main import app
        from gateway.store import get_local_api_key

        app.dependency_overrides[get_db] = _mock_db_session

        from fastapi.testclient import TestClient
        api_key = get_local_api_key()
        client = TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
        return client, app, commit_mock

    def test_get_preview_does_not_expose_last_four(self, tmp_path, monkeypatch) -> None:
        secret = "sk-ant-api03-ABCDEFGHIJKLMNOP-XYZ9"
        from gateway.main import app

        client, app, _ = self._make_client(monkeypatch, tmp_path, secret)
        try:
            resp = client.get("/api/user/secrets")
        finally:
            from gateway.db.engine import get_db
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        preview = body["anthropic_key_preview"]
        assert preview is not None
        assert preview.startswith("sk-ant-a")
        assert preview.endswith("...")
        assert "XYZ9" not in preview

    def test_put_preview_does_not_expose_last_four(self, tmp_path, monkeypatch) -> None:
        secret = "sk-ant-api03-ABCDEFGHIJKLMNOP-XYZ9"
        from gateway.main import app

        encryption_key = Fernet.generate_key()
        monkeypatch.setenv("SP_ENCRYPTION_KEY", encryption_key.decode())
        monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        import gateway.store.crypto as crypto
        monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)

        # For PUT, row starts empty (no existing secret)
        row = MagicMock()
        row.org_id = "local"
        row.user_id = "local"
        row.anthropic_api_key_enc = None
        row.updated_at = time.time()

        commit_mock = AsyncMock()

        async def _mock_db_session():
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = row
            session.execute = AsyncMock(return_value=result)
            session.commit = commit_mock
            yield session

        from fastapi.testclient import TestClient

        from gateway.db.engine import get_db
        from gateway.store import get_local_api_key

        app.dependency_overrides[get_db] = _mock_db_session
        try:
            api_key = get_local_api_key()
            client = TestClient(app, headers={"Authorization": f"Bearer {api_key}"})

            resp = client.put(
                "/api/user/secrets",
                json={"anthropic_api_key": secret},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        preview = body["anthropic_key_preview"]
        assert preview is not None
        assert preview.startswith("sk-ant-a")
        assert preview.endswith("...")
        assert "XYZ9" not in preview

    def test_put_short_key_returns_masked(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        import gateway.store.crypto as crypto
        monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)

        from gateway.store.crypto import _encrypt

        row = MagicMock()
        row.org_id = "local"
        row.user_id = "local"
        row.anthropic_api_key_enc = None
        row.updated_at = time.time()

        async def _mock_db_session():
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = row
            session.execute = AsyncMock(return_value=result)
            session.commit = AsyncMock()
            yield session

        from fastapi.testclient import TestClient

        from gateway.db.engine import get_db
        from gateway.main import app
        from gateway.store import get_local_api_key

        app.dependency_overrides[get_db] = _mock_db_session
        try:
            api_key = get_local_api_key()
            client = TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
            resp = client.put(
                "/api/user/secrets",
                json={"anthropic_api_key": "short"},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        preview = body["anthropic_key_preview"]
        assert preview == "****"
