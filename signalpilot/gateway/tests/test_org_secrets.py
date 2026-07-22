from __future__ import annotations

import logging
import time

import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayOrgSecrets
from gateway.store import notebook_sessions as ns
from gateway.store import org_secrets


async def _session_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
    monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

    import gateway.store.crypto as crypto

    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_org_secret_preview_is_prefix_only() -> None:
    from gateway.api.org_secrets import _mask_preview

    secret = "sk-ant-api03-ABCDEFGHIJKLMNOP-XYZ9"
    preview = _mask_preview(secret)

    assert preview == "sk-ant-a..."
    assert "XYZ9" not in preview
    assert _mask_preview("short") == "****"


@pytest.mark.asyncio
async def test_org_anthropic_key_set_rotate_and_clear(tmp_path, monkeypatch) -> None:
    engine, Session = await _session_factory(tmp_path, monkeypatch)
    try:
        async with Session() as session:
            await org_secrets.set_org_anthropic_key(session, "org-1", "sk-ant-org-1")
            assert await org_secrets.get_org_anthropic_key(session, "org-1") == "sk-ant-org-1"

            await org_secrets.set_org_anthropic_key(session, "org-1", "sk-ant-org-2")
            assert await org_secrets.resolve_anthropic_key(session, "org-1") == "sk-ant-org-2"

            row = await org_secrets.clear_org_anthropic_key(session, "org-1")
            assert row is not None
            assert await org_secrets.get_org_anthropic_key(session, "org-1") is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_org_anthropic_key_migrates_old_ciphertext_on_read(tmp_path, monkeypatch) -> None:
    key_old = Fernet.generate_key()
    key_primary = Fernet.generate_key()
    monkeypatch.setenv("SP_ENCRYPTION_KEY", key_primary.decode())
    monkeypatch.setenv("SP_ENCRYPTION_KEY_OLD", key_old.decode())
    monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)

    import gateway.store.crypto as crypto

    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)

    old_ciphertext = Fernet(key_old).encrypt(b"sk-ant-old-org-key")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)

    try:
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            row = GatewayOrgSecrets(
                org_id="org-1",
                anthropic_api_key_enc=old_ciphertext,
                updated_at=time.time(),
            )
            session.add(row)
            await session.commit()

            assert await org_secrets.get_org_anthropic_key(session, "org-1") == "sk-ant-old-org-key"
            assert row.anthropic_api_key_enc != old_ciphertext
            assert Fernet(key_primary).decrypt(row.anthropic_api_key_enc).decode() == "sk-ant-old-org-key"
            with pytest.raises(InvalidToken):
                Fernet(key_old).decrypt(row.anthropic_api_key_enc)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_org_anthropic_key_corrupt_ciphertext_returns_none_without_leaking(
    tmp_path,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine, Session = await _session_factory(tmp_path, monkeypatch)
    try:
        async with Session() as session:
            row = GatewayOrgSecrets(
                org_id="org-1",
                anthropic_api_key_enc=b"not-a-valid-fernet-token",
                updated_at=time.time(),
            )
            session.add(row)
            await session.commit()

            with caplog.at_level(logging.INFO):
                assert await org_secrets.get_org_anthropic_key(session, "org-1") is None
            assert "not-a-valid-fernet-token" not in caplog.text
    finally:
        await engine.dispose()


def test_org_secrets_api_get_put_rotate_clear_and_mask(tmp_path, monkeypatch) -> None:
    from gateway.db.engine import get_db
    from gateway.main import app
    from gateway.store import get_local_api_key

    async def run() -> tuple[object, object]:
        return await _session_factory(tmp_path, monkeypatch)

    import asyncio

    engine, Session = asyncio.run(run())

    async def _mock_db_session():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = _mock_db_session
    try:
        api_key = get_local_api_key()
        client = TestClient(app, headers={"Authorization": f"Bearer {api_key}"})

        unset = client.get("/api/org/secrets")
        assert unset.status_code == 200
        assert unset.json() == {"has_key": False, "key_preview": None, "updated_at": None}

        secret = "sk-ant-api03-ABCDEFGHIJKLMNOP-XYZ9"
        set_resp = client.put("/api/org/secrets", json={"anthropic_api_key": secret})
        assert set_resp.status_code == 200
        set_body = set_resp.json()
        assert set_body["has_key"] is True
        assert set_body["key_preview"] == "sk-ant-a..."
        assert secret not in set_resp.text
        assert "XYZ9" not in set_resp.text

        runtime_resp = client.get("/api/org/secrets/anthropic-key")
        assert runtime_resp.status_code == 200
        assert runtime_resp.json() == {"anthropic_api_key": secret}

        rotate_resp = client.put("/api/org/secrets", json={"anthropic_api_key": "sk-ant-rotated-SECRET"})
        assert rotate_resp.status_code == 200
        assert rotate_resp.json()["key_preview"] == "sk-ant-r..."
        assert "SECRET" not in rotate_resp.text

        clear_resp = client.put("/api/org/secrets", json={"anthropic_api_key": None})
        assert clear_resp.status_code == 200
        assert clear_resp.json()["has_key"] is False

        empty_clear_resp = client.put("/api/org/secrets", json={"anthropic_api_key": ""})
        assert empty_clear_resp.status_code == 200
        assert empty_clear_resp.json()["has_key"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)
        asyncio.run(engine.dispose())


def test_org_secrets_api_update_stops_active_notebook_sessions(tmp_path, monkeypatch) -> None:
    from gateway.api import org_secrets as org_secrets_api
    from gateway.db.engine import get_db
    from gateway.main import app
    from gateway.store import get_local_api_key

    async def run() -> tuple[object, object]:
        return await _session_factory(tmp_path, monkeypatch)

    import asyncio

    engine, Session = asyncio.run(run())

    async def seed_sessions() -> None:
        async with Session() as session:
            active = await ns.create_session(
                session,
                org_id="local",
                user_id="user-1",
                project_id=None,
                branch="main",
                pod_name="nb-local",
            )
            await ns.update_session_status(
                session,
                session_id=active.id,
                org_id="local",
                status="running",
                pod_ip="10.0.0.1",
                pod_ip_internal="10.0.0.1",
            )
            other = await ns.create_session(
                session,
                org_id="other",
                user_id="user-2",
                project_id=None,
                branch="main",
                pod_name="nb-other",
            )
            await ns.update_session_status(
                session,
                session_id=other.id,
                org_id="other",
                status="running",
                pod_ip="10.0.0.2",
                pod_ip_internal="10.0.0.2",
            )

    asyncio.run(seed_sessions())

    class FakeOrchestrator:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, str]] = []
            self.closed = False

        async def delete_pod(self, pod_name: str, *, org_id: str) -> bool:
            self.deleted.append((pod_name, org_id))
            return True

        async def close(self) -> None:
            self.closed = True

    fake_orch = FakeOrchestrator()

    async def fake_get_orchestrator() -> FakeOrchestrator:
        return fake_orch

    async def _mock_db_session():
        async with Session() as session:
            yield session

    monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
    monkeypatch.setattr(org_secrets_api, "_get_orchestrator", fake_get_orchestrator)
    app.dependency_overrides[get_db] = _mock_db_session
    try:
        api_key = get_local_api_key()
        client = TestClient(app, headers={"Authorization": f"Bearer {api_key}"})

        resp = client.put("/api/org/secrets", json={"anthropic_api_key": "sk-ant-api03-SECRET"})
        assert resp.status_code == 200

        async def check_sessions() -> tuple[int, int]:
            async with Session() as session:
                local = await ns.list_active_sessions_for_org(session, org_id="local")
                other = await ns.list_active_sessions_for_org(session, org_id="other")
                return len(local), len(other)

        local_active, other_active = asyncio.run(check_sessions())
        assert local_active == 0
        assert other_active == 1
        assert fake_orch.deleted == [("nb-local", "local")]
        assert fake_orch.closed is True
    finally:
        app.dependency_overrides.pop(get_db, None)
        asyncio.run(engine.dispose())


@pytest.mark.asyncio
async def test_org_secrets_api_corrupt_ciphertext_returns_unset(tmp_path, monkeypatch) -> None:
    engine, Session = await _session_factory(tmp_path, monkeypatch)
    try:
        async with Session() as session:
            session.add(
                GatewayOrgSecrets(
                    org_id="local",
                    anthropic_api_key_enc=b"bad-ciphertext",
                    updated_at=time.time(),
                )
            )
            await session.commit()

        from gateway.db.engine import get_db
        from gateway.main import app
        from gateway.store import get_local_api_key

        async def _mock_db_session():
            async with Session() as session:
                yield session

        app.dependency_overrides[get_db] = _mock_db_session
        try:
            api_key = get_local_api_key()
            client = TestClient(app, headers={"Authorization": f"Bearer {api_key}"})
            resp = client.get("/api/org/secrets")
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_key"] is False
        assert body["key_preview"] is None
        assert "bad-ciphertext" not in resp.text
    finally:
        await engine.dispose()
