"""HTTP-path test: GET /api/user/secrets re-encrypts old-key ciphertext on read.

Closes R9 case-6 gap: verifies the migration callsite in
gateway.api.user_secrets.get_secrets actually fires when the route is hit.
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient


class TestUserSecretsRouteMigratesOldKeyCiphertext:
    def test_get_secrets_reencrypts_old_key_row_to_primary(
        self, tmp_path, monkeypatch
    ):
        # ── Arrange keys: B is primary, A is old ──
        key_old = Fernet.generate_key()
        key_primary = Fernet.generate_key()
        monkeypatch.setenv("SP_ENCRYPTION_KEY", key_primary.decode())
        monkeypatch.setenv("SP_ENCRYPTION_KEY_OLD", key_old.decode())
        monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

        # Reset MultiFernet cache so new env is picked up.
        import gateway.store.crypto as crypto
        monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)

        # ── Build an "old-key" ciphertext directly with key A. ──
        plaintext_secret = "sk-ant-abcdef1234567890"
        old_ciphertext = Fernet(key_old).encrypt(plaintext_secret.encode())

        # ── Build a mutable row that mimics GatewayUserSecrets. ──
        row = MagicMock()
        row.org_id = "local"
        row.user_id = "local"
        row.anthropic_api_key_enc = old_ciphertext
        row.updated_at = time.time()

        # ── Mock the async DB session so .execute() returns our row,
        #    and .commit() is observable. ──
        commit_mock = AsyncMock()

        async def _mock_db_session():
            session = AsyncMock()
            result = MagicMock()
            result.scalar_one_or_none.return_value = row
            session.execute = AsyncMock(return_value=result)
            session.commit = commit_mock
            yield session

        # ── Wire the override. Use whichever symbol `StoreD` depends on
        #    (verified in gateway/api/deps.py). ──
        from gateway.db.engine import get_db
        from gateway.main import app
        from gateway.store import get_local_api_key

        app.dependency_overrides[get_db] = _mock_db_session
        try:
            api_key = get_local_api_key()
            client = TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
            resp = client.get("/api/user/secrets")
        finally:
            app.dependency_overrides.pop(get_db, None)

        # ── Assert: route succeeded and reports a key exists. ──
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_anthropic_key"] is True

        # ── Assert: row was mutated to a NEW ciphertext, distinct from the old one. ──
        assert row.anthropic_api_key_enc != old_ciphertext

        # ── Assert: commit fired (migration write-back actually persisted). ──
        commit_mock.assert_awaited()

        # ── Assert: new ciphertext decrypts under the PRIMARY key directly. ──
        recovered = Fernet(key_primary).decrypt(row.anthropic_api_key_enc).decode()
        assert recovered == plaintext_secret

        # ── Assert: new ciphertext does NOT decrypt under the OLD key alone. ──
        with pytest.raises(InvalidToken):
            Fernet(key_old).decrypt(row.anthropic_api_key_enc)
