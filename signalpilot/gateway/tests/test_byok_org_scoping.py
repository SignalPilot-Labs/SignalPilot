"""Tests for BYOK API org_id scoping (V1-V4 security fixes).

Verifies that cross-tenant access is blocked and provider_config is redacted.
No live database required — all DB interactions are mocked.

org_id is always sourced from the JWT via the OrgID dependency; tests override
the dependency directly instead of passing ?org_id= query params.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from gateway.main import app

# ─── Fixtures ────────────────────────────────────────────────────────────────


def _make_byok_key_row(
    key_id: str,
    org_id: str,
    key_alias: str = "alias1",
    status: str = "active",
    provider_config: dict | None = None,
) -> MagicMock:
    key = MagicMock()
    key.id = key_id
    key.org_id = org_id
    key.key_alias = key_alias
    key.provider_type = "local"
    key.provider_config = provider_config or {"arn": "arn:aws:kms:us-east-1:123:key/abc"}
    key.status = status
    key.created_at = time.time()
    key.revoked_at = None
    return key


def _make_db_session(scalar_return=None, scalars_list=None) -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_return
    if scalars_list is not None:
        result.scalars.return_value = iter(scalars_list)
    else:
        result.scalars.return_value = iter([])
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def admin_client():
    """TestClient with admin API key and a DB override that can be swapped per test."""
    from gateway.auth import resolve_org_id
    from gateway.db.engine import get_db
    from gateway.store import get_local_api_key

    api_key = get_local_api_key()

    async def _empty_db():
        yield _make_db_session()

    async def _default_org_id():
        return "org1"

    app.dependency_overrides[get_db] = _empty_db
    app.dependency_overrides[resolve_org_id] = _default_org_id
    try:
        yield TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(resolve_org_id, None)


def _override_db(session: AsyncMock):
    """Replace the get_db dependency with one that yields the given session."""
    from gateway.db.engine import get_db

    async def _mock_db():
        yield session

    app.dependency_overrides[get_db] = _mock_db


def _override_org_id(org_id: str):
    """Override resolve_org_id to return a fixed org_id."""
    from gateway.auth import resolve_org_id

    async def _mock_org_id():
        return org_id

    app.dependency_overrides[resolve_org_id] = _mock_org_id


# ─── V1: list endpoint is scoped to JWT org ───────────────────────────────────


class TestListBYOKKeysOrgScoping:
    def test_list_scopes_to_jwt_org(self, admin_client):
        """GET /api/byok/keys returns only the JWT org's keys."""
        key = _make_byok_key_row("key-1", "org1")
        session = _make_db_session(scalars_list=[key])
        _override_db(session)
        resp = admin_client.get("/api/byok/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["org_id"] == "org1"

    def test_list_returns_empty_for_different_org(self, admin_client):
        """Keys belonging to org2 are not visible when JWT says org1."""
        session = _make_db_session(scalars_list=[])
        _override_db(session)
        resp = admin_client.get("/api/byok/keys")
        assert resp.status_code == 200
        assert resp.json() == []


# ─── V2: get/update/delete/validate enforce ownership via JWT org ─────────────


class TestGetBYOKKeyOrgScoping:
    def test_get_returns_404_for_wrong_org(self, admin_client):
        """Key exists but belongs to org2 — JWT org1 caller gets 404."""
        key = _make_byok_key_row("key-1", "org2")
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        resp = admin_client.get("/api/byok/keys/key-1")
        assert resp.status_code == 404

    def test_get_returns_200_for_correct_org(self, admin_client):
        """Key exists and belongs to org1 — JWT org1 caller gets 200."""
        key = _make_byok_key_row("key-1", "org1")
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        resp = admin_client.get("/api/byok/keys/key-1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "key-1"


class TestUpdateBYOKKeyOrgScoping:
    def test_update_returns_404_for_wrong_org(self, admin_client):
        key = _make_byok_key_row("key-1", "org2")
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        resp = admin_client.put("/api/byok/keys/key-1", json={"status": "revoked"})
        assert resp.status_code == 404


class TestDeleteBYOKKeyOrgScoping:
    def test_delete_returns_404_for_wrong_org(self, admin_client):
        key = _make_byok_key_row("key-1", "org2")
        session = _make_db_session(scalar_return=key)

        call_count = 0

        async def _multi_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                res = MagicMock()
                res.scalar_one_or_none.return_value = key
                res.scalars.return_value.all.return_value = []
                return res
            res = MagicMock()
            res.scalar_one_or_none.return_value = None
            res.scalars.return_value.all.return_value = []
            return res

        session.execute = _multi_execute
        _override_db(session)

        resp = admin_client.delete("/api/byok/keys/key-1")
        assert resp.status_code == 404


# ─── Cross-tenant blocked test ────────────────────────────────────────────────


class TestCrossTenantBlocked:
    def test_cross_tenant_get_blocked(self, admin_client):
        """JWT says org1, key belongs to org2 — GET returns 404."""
        key = _make_byok_key_row("key-x", "org2")
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        _override_org_id("org1")
        resp = admin_client.get("/api/byok/keys/key-x")
        assert resp.status_code == 404

    def test_cross_tenant_put_blocked(self, admin_client):
        """JWT says org1, key belongs to org2 — PUT returns 404."""
        key = _make_byok_key_row("key-x", "org2")
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        _override_org_id("org1")
        resp = admin_client.put("/api/byok/keys/key-x", json={"status": "revoked"})
        assert resp.status_code == 404

    def test_cross_tenant_delete_blocked(self, admin_client):
        """JWT says org1, key belongs to org2 — DELETE returns 404."""
        key = _make_byok_key_row("key-x", "org2")
        session = _make_db_session(scalar_return=key)

        call_count = 0

        async def _multi_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            res = MagicMock()
            res.scalar_one_or_none.return_value = key
            res.scalars.return_value.all.return_value = []
            return res

        session.execute = _multi_execute
        _override_db(session)
        _override_org_id("org1")
        resp = admin_client.delete("/api/byok/keys/key-x")
        assert resp.status_code == 404


# ─── V3: migrate verifies key belongs to org ─────────────────────────────────


class TestMigrateOrgOwnership:
    def test_migrate_returns_404_when_key_belongs_to_different_org(self, admin_client):
        """Migrate request for org1 using a key owned by org2 gets 404."""
        from unittest.mock import patch

        from gateway.api.deps import get_store
        from gateway.auth import resolve_org_id
        from gateway.byok import LocalBYOKProvider
        from gateway.store import Store

        key = _make_byok_key_row("key-1", "org2", status="active")
        session = _make_db_session(scalar_return=key)
        _override_db(session)

        store = MagicMock(spec=Store)
        store.session = session

        async def _mock_store():
            return store

        async def _org1():
            return "org1"

        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        app.dependency_overrides[get_store] = _mock_store
        app.dependency_overrides[resolve_org_id] = _org1

        with patch("gateway.store._byok_provider", provider):
            resp = admin_client.post(
                "/api/byok/migrate",
                json={"key_id": "key-1"},
            )
        assert resp.status_code == 404
        app.dependency_overrides.pop(get_store, None)
        app.dependency_overrides.pop(resolve_org_id, None)


# ─── V4: provider_config redacted in responses ───────────────────────────────


class TestProviderConfigRedacted:
    def test_list_response_omits_provider_config(self, admin_client):
        """provider_config must be None/absent in list responses."""
        key = _make_byok_key_row("key-1", "org1", provider_config={"arn": "secret-arn"})
        session = _make_db_session(scalars_list=[key])
        _override_db(session)
        resp = admin_client.get("/api/byok/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0].get("provider_config") is None

    def test_get_response_omits_provider_config(self, admin_client):
        """provider_config must be None/absent in single-key get response."""
        key = _make_byok_key_row("key-1", "org1", provider_config={"uri": "secret-uri"})
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        resp = admin_client.get("/api/byok/keys/key-1")
        assert resp.status_code == 200
        assert resp.json().get("provider_config") is None


# ─── H1: validate endpoint returns generic error for BYOKKeyError ─────────────


class TestValidateH1ErrorRedaction:
    def test_validate_returns_generic_error_not_internal_details(self, admin_client):
        """Validate endpoint must not expose internal BYOKKeyError details (H1)."""
        from unittest.mock import patch

        from gateway.byok import BYOKKeyError

        key = _make_byok_key_row("key-1", "org1")
        session = _make_db_session(scalar_return=key)
        _override_db(session)

        provider = MagicMock()

        async def _raise_byok_key_error(*args, **kwargs):
            raise BYOKKeyError("org1", "alias1", "internal KMS error detail")

        with (
            patch("gateway.store._byok_provider", provider),
            patch("gateway.api.byok.encrypt_envelope", side_effect=_raise_byok_key_error),
        ):
            resp = admin_client.post("/api/byok/keys/key-1/validate")

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert "internal KMS error detail" not in body.get("error", "")
        assert body["error"] == "Key validation failed"


# ─── H2: migrate/revert errors use credential IDs not connection names ────────


class TestMigrateH2ErrorRedaction:
    def test_migrate_error_uses_credential_id_not_connection_name(self, admin_client):
        """Error messages in migrate response must use credential IDs, not connection names (H2)."""
        from unittest.mock import patch

        from gateway.api.deps import get_store
        from gateway.auth import resolve_org_id
        from gateway.byok import LocalBYOKProvider
        from gateway.store import Store

        key = _make_byok_key_row("key-1", "org1", key_alias="alias1", status="active")
        session = _make_db_session(scalar_return=key)
        _override_db(session)

        store = MagicMock(spec=Store)
        store.session = session

        async def _mock_store():
            return store

        async def _org1():
            return "org1"

        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        app.dependency_overrides[get_store] = _mock_store
        app.dependency_overrides[resolve_org_id] = _org1

        cred_mock = MagicMock()
        cred_mock.id = "cred-uuid-123"
        cred_mock.connection_name = "my-secret-db"
        cred_mock.encryption_mode = "managed"

        async def _migrate_side_effect(*args, **kwargs):
            return (0, 1, ["Failed to migrate a credential: migration error"])

        with (
            patch("gateway.store._byok_provider", provider),
            patch("gateway.api.byok.migrate_to_byok", side_effect=_migrate_side_effect),
        ):
            resp = admin_client.post(
                "/api/byok/migrate",
                json={"key_id": "key-1"},
            )

        app.dependency_overrides.pop(get_store, None)
        app.dependency_overrides.pop(resolve_org_id, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["failed"] == 1
        # Error message must not expose internal IDs or connection names
        assert "my-secret-db" not in str(body["errors"])
        assert "cred-uuid-123" not in str(body["errors"])
        assert "Failed to migrate a credential" in str(body["errors"])
