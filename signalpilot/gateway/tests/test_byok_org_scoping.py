"""Tests for BYOK API org_id scoping (V1-V4 security fixes).

Verifies that cross-tenant access is blocked and provider_config is redacted.
No live database required — all DB interactions are mocked.
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
    from gateway.db.engine import get_db
    from gateway.store import get_local_api_key

    api_key = get_local_api_key()

    async def _empty_db():
        yield _make_db_session()

    app.dependency_overrides[get_db] = _empty_db
    try:
        yield TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
    finally:
        app.dependency_overrides.pop(get_db, None)


def _override_db(session: AsyncMock):
    """Replace the get_db dependency with one that yields the given session."""
    from gateway.db.engine import get_db

    async def _mock_db():
        yield session

    app.dependency_overrides[get_db] = _mock_db


# ─── V1: list endpoint requires org_id ───────────────────────────────────────

class TestListBYOKKeysOrgRequired:

    def test_list_without_org_id_returns_422(self, admin_client):
        """GET /api/byok/keys without org_id must return 422 (required param)."""
        resp = admin_client.get("/api/byok/keys")
        assert resp.status_code == 422

    def test_list_with_org_id_scopes_to_that_org(self, admin_client):
        """GET /api/byok/keys?org_id=org1 returns only that org's keys."""
        key = _make_byok_key_row("key-1", "org1")
        session = _make_db_session(scalars_list=[key])
        _override_db(session)
        resp = admin_client.get("/api/byok/keys?org_id=org1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["org_id"] == "org1"


# ─── V2: get/update/delete/validate require org_id and enforce ownership ─────

class TestGetBYOKKeyOrgScoping:

    def test_get_without_org_id_returns_422(self, admin_client):
        """GET /api/byok/keys/{key_id} without org_id must return 422."""
        resp = admin_client.get("/api/byok/keys/some-key-id")
        assert resp.status_code == 422

    def test_get_returns_404_for_wrong_org(self, admin_client):
        """Key exists but belongs to org2 — org1 caller gets 404."""
        key = _make_byok_key_row("key-1", "org2")
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        resp = admin_client.get("/api/byok/keys/key-1?org_id=org1")
        assert resp.status_code == 404

    def test_get_returns_200_for_correct_org(self, admin_client):
        """Key exists and belongs to org1 — org1 caller gets 200."""
        key = _make_byok_key_row("key-1", "org1")
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        resp = admin_client.get("/api/byok/keys/key-1?org_id=org1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "key-1"


class TestUpdateBYOKKeyOrgScoping:

    def test_update_without_org_id_returns_422(self, admin_client):
        resp = admin_client.put("/api/byok/keys/key-1", json={"status": "revoked"})
        assert resp.status_code == 422

    def test_update_returns_404_for_wrong_org(self, admin_client):
        key = _make_byok_key_row("key-1", "org2")
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        resp = admin_client.put(
            "/api/byok/keys/key-1?org_id=org1", json={"status": "revoked"}
        )
        assert resp.status_code == 404


class TestDeleteBYOKKeyOrgScoping:

    def test_delete_without_org_id_returns_422(self, admin_client):
        resp = admin_client.delete("/api/byok/keys/key-1")
        assert resp.status_code == 422

    def test_delete_returns_404_for_wrong_org(self, admin_client):
        key = _make_byok_key_row("key-1", "org2")
        # Also need credential check to return empty
        session = _make_db_session(scalar_return=key)

        call_count = 0

        async def _multi_execute(stmt, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: key lookup
                res = MagicMock()
                res.scalar_one_or_none.return_value = key
                res.scalars.return_value.all.return_value = []
                return res
            # Should not reach here if org check triggers 404 first
            res = MagicMock()
            res.scalar_one_or_none.return_value = None
            res.scalars.return_value.all.return_value = []
            return res

        session.execute = _multi_execute
        _override_db(session)

        resp = admin_client.delete("/api/byok/keys/key-1?org_id=org1")
        assert resp.status_code == 404


# ─── V3: migrate verifies key belongs to org ─────────────────────────────────

class TestMigrateOrgOwnership:

    def test_migrate_returns_404_when_key_belongs_to_different_org(self, admin_client):
        """Migrate request for org1 using a key owned by org2 gets 404."""
        from unittest.mock import patch
        from gateway.api.deps import get_store
        from gateway.store import Store
        from gateway.byok import LocalBYOKProvider

        key = _make_byok_key_row("key-1", "org2", status="active")
        session = _make_db_session(scalar_return=key)
        _override_db(session)

        store = MagicMock(spec=Store)
        store.session = session

        async def _mock_store():
            return store

        provider = LocalBYOKProvider()
        provider.register_key("org1", "alias1")

        app.dependency_overrides[get_store] = _mock_store

        with patch("gateway.store._byok_provider", provider):
            resp = admin_client.post(
                "/api/byok/migrate",
                json={"org_id": "org1", "key_id": "key-1"},
            )
        assert resp.status_code == 404
        app.dependency_overrides.pop(get_store, None)


# ─── V4: provider_config redacted in responses ───────────────────────────────

class TestProviderConfigRedacted:

    def test_list_response_omits_provider_config(self, admin_client):
        """provider_config must be None/absent in list responses."""
        key = _make_byok_key_row("key-1", "org1", provider_config={"arn": "secret-arn"})
        session = _make_db_session(scalars_list=[key])
        _override_db(session)
        resp = admin_client.get("/api/byok/keys?org_id=org1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0].get("provider_config") is None

    def test_get_response_omits_provider_config(self, admin_client):
        """provider_config must be None/absent in single-key get response."""
        key = _make_byok_key_row("key-1", "org1", provider_config={"uri": "secret-uri"})
        session = _make_db_session(scalar_return=key)
        _override_db(session)
        resp = admin_client.get("/api/byok/keys/key-1?org_id=org1")
        assert resp.status_code == 200
        assert resp.json().get("provider_config") is None
