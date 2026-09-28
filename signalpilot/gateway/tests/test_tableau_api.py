"""Tableau API: admin settings (verify-before-save, secret hygiene, admin gate),
runtime gate (run token + capability + active integration), store round trip,
and the chat execution feature flag."""

from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase, GatewayTableauIntegration, GatewayWorkspaceProject
from gateway.standalone_chat import execution as chat_execution
from gateway.store import standalone_chat as chat_store
from gateway.store import tableau as tableau_store
from gateway.tableau import client as tableau_client
from gateway.tableau import service as tableau_service

from .tableau_support import PAT_SECRET, SERVER, SITE_ID, FakeTableau, _json

SITE_URL = f"{SERVER}/#/site/mysite/home"
RUN_AUTH = {"auth_method": "notebook_session", "scopes": ["read", "execute"], "capabilities": ["tableau"]}


@pytest_asyncio.fixture
async def factory(tmp_path, monkeypatch):
    import gateway.store.crypto as crypto

    monkeypatch.setenv("SP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SP_ENCRYPTION_KEY_OLD", raising=False)
    monkeypatch.setenv("SP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(crypto, "_CACHED_MULTIFERNET", None)
    tableau_client.clear_token_cache()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    tableau_client.clear_token_cache()
    await engine.dispose()


class FakeStore:
    """The slice of Store the Tableau routes use."""

    def __init__(self, session: AsyncSession, allowed: str | None) -> None:
        self.session = session
        self.org_id = "org-1"
        self.user_id = "user-1"
        self.allowed_connection_name = allowed
        self.audit: list[Any] = []

    async def append_audit(self, entry: Any) -> None:
        self.audit.append(entry)

    async def get_connection(self, name: str) -> Any:
        if self.allowed_connection_name and name != self.allowed_connection_name:
            raise ValueError("Connection is outside this execution's allowed scope")
        if name != "rds":
            return None
        return SimpleNamespace(
            db_type="mssql", host="db.example.com", port=1433, database="Analytics", username="svc", ssl=False
        )

    async def get_connection_string(self, name: str) -> str | None:
        return "mssql://svc:db%40password@db.example.com:1433/Analytics" if name == "rds" else None


@pytest.fixture
def api(factory, monkeypatch):
    """(TestClient, state, fake Tableau). ``state`` drives auth, org role, and the chat connection."""
    from gateway.api.deps import get_store
    from gateway.api.tableau import router
    from gateway.auth.user import require_org_admin
    from gateway.security.scope_guard import _resolve_user_id

    fake = FakeTableau()
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/users/user-1")] = _json(
        {"user": {"name": "owner@example.com", "siteRole": "SiteAdministratorCreator"}}
    )
    monkeypatch.setattr(tableau_service, "transport_override", httpx.MockTransport(fake.handler))
    state: dict[str, Any] = {"auth": None, "admin": True, "allowed": "rds", "stores": []}
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        request.state.auth = state["auth"]
        return await call_next(request)

    async def store_dep():
        async with factory() as session:
            store = FakeStore(session, state["allowed"])
            state["stores"].append(store)
            yield store

    def admin_dep() -> str:
        if not state["admin"]:
            raise HTTPException(status_code=403, detail="Organization admin role required")
        return "org:admin"

    app.include_router(router)
    app.dependency_overrides[get_store] = store_dep
    app.dependency_overrides[_resolve_user_id] = lambda: "user-1"
    app.dependency_overrides[require_org_admin] = admin_dep
    with TestClient(app) as client:
        yield client, state, fake


def _connect(client: TestClient, **extra: Any) -> httpx.Response:
    return client.put(
        "/api/tableau/integration", json={"site_url": SITE_URL, "pat_name": "pat", "pat_secret": PAT_SECRET, **extra}
    )


# ── Admin ───────────────────────────────────────────────────────────────────


def test_not_configured_shape(api) -> None:
    client, _, _ = api
    body = client.get("/api/tableau/integration").json()
    assert body["configured"] is False and body["enabled"] is False and body["active"] is False
    assert body["server_url"] is None and body["status"] is None


def test_put_verifies_before_saving(api) -> None:
    client, _, fake = api
    bad = client.put("/api/tableau/integration", json={"site_url": SITE_URL, "pat_name": "pat", "pat_secret": "nope"})
    assert bad.status_code == 400 and "Signin Error" in bad.json()["detail"]
    assert client.get("/api/tableau/integration").json()["configured"] is False
    missing = client.put("/api/tableau/integration", json={"site_url": SITE_URL, "pat_name": "pat"})
    assert missing.status_code == 400 and "pat_secret" in missing.json()["detail"]
    insecure = client.put(
        "/api/tableau/integration", json={"site_url": "http://tab.example.com", "pat_name": "p", "pat_secret": "x"}
    )
    assert insecure.status_code == 400

    ok = _connect(client)
    assert ok.status_code == 200, ok.text
    info = ok.json()
    assert info["configured"] and info["enabled"] and info["active"] and info["status"] == "ok"
    assert info["server_url"] == SERVER and info["site_content_url"] == "mysite"
    assert info["site_url"] == f"{SERVER}/#/site/mysite"
    assert info["user_name"] == "owner@example.com" and info["site_role"] == "SiteAdministratorCreator"
    assert PAT_SECRET not in ok.text and PAT_SECRET not in client.get("/api/tableau/integration").text
    signin = next(r for r in fake.requests if r.url.path.endswith("/auth/signin"))
    assert json.loads(signin.content)["credentials"]["site"] == {"contentUrl": "mysite"}


def test_put_without_secret_keeps_existing(api, factory) -> None:
    client, state, _ = api
    assert _connect(client).status_code == 200
    again = client.put("/api/tableau/integration", json={"site_url": SITE_URL, "pat_name": "pat", "enabled": False})
    assert again.status_code == 200 and again.json()["enabled"] is False and again.json()["active"] is False
    assert state["stores"][-1].audit[-1].event_type == "tableau_integration_save"
    assert PAT_SECRET not in json.dumps(state["stores"][-1].audit[-1].metadata)


def test_admin_writes_require_admin(api) -> None:
    client, state, _ = api
    state["admin"] = False
    assert _connect(client).status_code == 403
    assert client.patch("/api/tableau/integration", json={"enabled": False}).status_code == 403
    assert client.post("/api/tableau/integration/test").status_code == 403
    assert client.delete("/api/tableau/integration").status_code == 403
    assert client.get("/api/tableau/integration").status_code == 200  # reads stay open to members


def test_patch_test_delete(api) -> None:
    client, _, fake = api
    assert client.patch("/api/tableau/integration", json={"enabled": False}).status_code == 404
    assert _connect(client).status_code == 200
    off = client.patch("/api/tableau/integration", json={"enabled": False}).json()
    assert off["enabled"] is False and off["active"] is False and off["status"] == "ok"
    on = client.patch("/api/tableau/integration", json={"enabled": True}).json()
    assert on["active"] is True
    tested = client.post("/api/tableau/integration/test")
    assert tested.status_code == 200 and tested.json()["status"] == "ok"
    assert tableau_client._TOKENS.get("org-1") is not None
    assert client.delete("/api/tableau/integration").status_code == 204
    assert client.get("/api/tableau/integration").json()["configured"] is False
    assert "org-1" not in tableau_client._TOKENS
    assert any(r.url.path.endswith("/auth/signout") for r in fake.requests)


# ── Runtime gate ────────────────────────────────────────────────────────────


def test_runtime_rejects_user_tokens_and_missing_capability(api) -> None:
    client, state, _ = api
    assert _connect(client).status_code == 200
    state["auth"] = None  # a signed-in user, not a run
    resp = client.get("/api/tableau/runtime/search", params={"q": "x"})
    assert resp.status_code == 403 and "run" in resp.json()["detail"]
    state["auth"] = {"auth_method": "api_key", "scopes": ["read", "execute"]}
    assert client.get("/api/tableau/runtime/projects").status_code == 403
    state["auth"] = {**RUN_AUTH, "capabilities": ["mcp_proxy"]}
    resp = client.get("/api/tableau/runtime/projects")
    assert resp.status_code == 403 and "capability" in resp.json()["detail"]


def test_runtime_rejects_inactive_integration(api) -> None:
    client, state, _ = api
    state["auth"] = RUN_AUTH
    resp = client.get("/api/tableau/runtime/projects")
    assert resp.status_code == 403 and "integration" in resp.json()["detail"]
    state["auth"] = None
    assert _connect(client, enabled=False).status_code == 200
    state["auth"] = RUN_AUTH
    resp = client.get("/api/tableau/runtime/projects")
    assert resp.status_code == 403 and "integration" in resp.json()["detail"]


def test_runtime_routes_happy_path(api) -> None:
    client, state, fake = api
    assert _connect(client).status_code == 200
    state["auth"] = RUN_AUTH
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/projects")] = _json(
        {"pagination": {"totalAvailable": "1"}, "projects": {"project": [{"id": "p1", "name": "default"}]}}
    )
    assert client.get("/api/tableau/runtime/projects").json() == {
        "projects": [{"id": "p1", "name": "default", "parent_id": None}]
    }

    conn = client.get("/api/tableau/runtime/connections/rds").json()
    assert conn["tableau_class"] == "sqlserver" and conn["sql_server_address"] == "db.example.com,1433"
    assert "password" not in conn and "db@password" not in json.dumps(conn)
    assert client.get("/api/tableau/runtime/connections/other").status_code == 403  # outside the run's scope

    # A workbook name with a slash and a non-ASCII character, sent URL-encoded.
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks")] = _json(
        {"pagination": {"totalAvailable": "1"}, "workbooks": {"workbook": [{"id": "w1", "name": "P&L / Café"}]}}
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Book.twb", b"<workbook/>")
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks/w1/content")] = lambda _r: httpx.Response(
        200, content=buf.getvalue()
    )
    resp = client.get("/api/tableau/runtime/workbooks/P%26L%20%2F%20Caf%C3%A9/content")
    assert resp.status_code == 200 and resp.content == b"<workbook/>"
    assert resp.headers["content-type"].startswith("application/xml")
    assert resp.headers["x-tableau-workbook-id"] == "w1"
    assert resp.headers["x-tableau-workbook-name"] == "P%26L%20%2F%20Caf%C3%A9"
    assert "filter" in dict(next(r for r in fake.requests if r.url.path.endswith("/workbooks")).url.params)

    missing = client.get("/api/tableau/runtime/views/nope/image")
    assert missing.status_code == 404 and "detail" in missing.json()


def test_runtime_publish_workbook_multipart(api) -> None:
    client, state, fake = api
    assert _connect(client).status_code == 200
    state["auth"] = RUN_AUTH
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/projects")] = _json(
        {"pagination": {"totalAvailable": "1"}, "projects": {"project": [{"id": "p1", "name": "default"}]}}
    )
    fake.routes[("POST", f"/api/3.29/sites/{SITE_ID}/workbooks")] = lambda _r: httpx.Response(
        201, json={"workbook": {"id": "wb-9", "name": "Book", "webpageUrl": "https://x"}}
    )
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks/wb-9/connections")] = _json(
        {
            "connections": {
                "connection": [
                    {
                        "id": "c1",
                        "type": "sqlserver",
                        "serverAddress": "db.example.com,1433",
                        "datasource": {"name": "Sales"},
                    }
                ]
            }
        }
    )
    puts: list[dict] = []
    fake.routes[("PUT", f"/api/3.29/sites/{SITE_ID}/workbooks/wb-9/connections/c1")] = lambda r: (
        puts.append(json.loads(r.content)) or httpx.Response(200, json={"connection": {}})
    )
    fake.routes[("GET", f"/api/3.29/sites/{SITE_ID}/workbooks/wb-9/views")] = _json({"views": {}})
    resp = client.post(
        "/api/tableau/runtime/workbooks",
        files={"file": ("book.twb", b"<workbook version='18.1'/>", "application/xml")},
        data={"name": "Book", "overwrite": "true", "show_tabs": "false"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == "wb-9" and body["credentials_embedded"] == ["Sales"] and body["unbound_connections"] == []
    assert body["project"] == {"id": "p1", "name": "default"} and body["site_references_rewritten"] == 0
    assert puts[0]["connection"]["password"] == "db@password"  # the run's own connection by default
    assert "db@password" not in resp.text


# ── Store + execution gating ────────────────────────────────────────────────


async def test_store_encrypts_secret_round_trip(factory) -> None:
    async with factory() as session:
        row = await tableau_store.save_integration(
            session,
            "org-9",
            server_url=SERVER,
            site_content_url="s",
            pat_name="p",
            pat_secret="very-secret",
            enabled=None,
            site_id="sid",
            user_name="u",
            site_role="Creator",
            user_id="user-1",
        )
        assert b"very-secret" not in row.pat_secret_enc
        assert await tableau_store.decrypt_secret(session, row) == "very-secret"
        assert "very-secret" not in json.dumps(tableau_store.info_dict(row))
        assert await tableau_store.is_active(session, "org-9") is True
        await tableau_store.set_enabled(session, row, False)
        assert await tableau_store.is_active(session, "org-9") is False
        assert await tableau_store.is_active(session, "org-none") is False


async def test_execution_flag_follows_integration(factory, monkeypatch) -> None:
    async with factory() as db:
        db.add(
            GatewayWorkspaceProject(
                id="project-a",
                org_id="org-a",
                name="rev",
                display_name="Rev",
                description="",
                connection_name="prod",
                source="managed",
                status="active",
                settings={},
                file_count=0,
                total_bytes=0,
                default_branch="main",
                created_at=1.0,
                updated_at=1.0,
            )
        )
        await db.commit()
        project = await db.get(GatewayWorkspaceProject, "project-a")
        _, run = await chat_store.create_conversation_with_run(
            db,
            org_id="org-a",
            user_id="user-a",
            project=project,
            branch="main",
            message="hi",
            commit_sha="a" * 40,
        )
        minted: dict[str, Any] = {}
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server")
        monkeypatch.setattr(
            chat_execution,
            "ensure_execution_runtime",
            AsyncMock(
                return_value=SimpleNamespace(
                    session_id="session-a", internal_base_url="http://notebook.internal", access_token=None
                )
            ),
        )
        monkeypatch.setattr(chat_execution, "mint_session_jwt", lambda **kw: minted.update(kw) or "jwt")
        monkeypatch.setattr(
            chat_execution, "get_gateway_settings", lambda: SimpleNamespace(sp_session_jwt_ttl_seconds=300)
        )

        async def prepare() -> Any:
            return await chat_execution.prepare_execution(
                db,
                run=run,
                worker_id="w",
                branch="main",
                connection_name="prod",
                commit_sha="a" * 40,
                prompt="p",
                messages=[],
                warm_context={},
            )

        off = await prepare()
        assert off.payload["features"]["tableau"] is False and "tableau" not in minted["capabilities"]

        db.add(
            GatewayTableauIntegration(
                org_id="org-a",
                server_url=SERVER,
                site_content_url="s",
                pat_name="p",
                pat_secret_enc=b"x",
                enabled=True,
                status="ok",
                created_at=1.0,
                updated_at=1.0,
            )
        )
        await db.commit()
        on = await prepare()
        assert on.payload["features"]["tableau"] is True and "tableau" in minted["capabilities"]


async def test_execution_flag_survives_db_errors() -> None:
    broken = SimpleNamespace(begin_nested=lambda: (_ for _ in ()).throw(RuntimeError("no table")))
    assert await chat_execution.tableau_active_for_org(broken, "org-a") is False
