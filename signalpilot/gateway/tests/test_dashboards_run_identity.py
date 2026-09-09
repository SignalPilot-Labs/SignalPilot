"""The chat sandbox reads the dashboard gallery with its run-scoped token.

Mints the same token ``standalone_chat.execution.prepare_execution`` hands
the sandbox (``execution_identity == "chat:<run_id>"``, subject = the run's
user) and drives the real app over HTTP: the three read routes answer with
the user's own visibility, every write route refuses the token.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api import dashboards as routes
from gateway.api.chat_routes import publish_dashboard as publish_routes
from gateway.auth.notebook_jwt import mint_session_jwt
from gateway.db.models import GatewayBase, GatewayWorkspaceProject
from gateway.store import standalone_chat as chat_store
from tests.dashboards_support import (
    ORG,
    OTHER_USER,
    PROJECT,
    USER,
    FakeExecutor,
    add_conversation_with_files,
    api_store,
    fake_manifest,
    fake_storage,
    publish_body,
)
from tests.mcp_connectors_support import isolated_app

_TEST_SECRET = "test-secret-for-dashboard-run-identity"
REFUSED = "This action requires an interactive user"


def _run_token(run_id: str, *, org_id: str = ORG, scopes: list[str] | None = None) -> str:
    """Exactly what ``prepare_execution`` mints for the sandbox."""
    return mint_session_jwt(
        user_id=USER,
        org_id=org_id,
        session_id="session-a",
        project_id=PROJECT,
        branch="main",
        connection_name="warehouse",
        commit_sha="a" * 40,
        capabilities=["query:read"],
        execution_identity=f"chat:{run_id}",
        scopes=scopes or ["read", "query", "execute", "write", "admin"],
        ttl=600,
    )


async def _other_users_conversation(db: AsyncSession, backend):
    """A second conversation on the same project, owned by OTHER_USER."""
    project = await db.get(GatewayWorkspaceProject, PROJECT)
    conversation, run = await chat_store.create_conversation_with_run(
        db, org_id=ORG, user_id=OTHER_USER, project=project, branch="main", message="Secret", commit_sha="b" * 40
    )
    for entry in fake_manifest(backend, run_id=run.id):
        data = backend.objects[entry.object_key]
        await chat_store.upsert_conversation_file(
            db,
            org_id=ORG,
            user_id=OTHER_USER,
            conversation_id=conversation.id,
            path=entry.path,
            filename=entry.filename,
            mime_type=None,
            byte_size=len(data),
            content_hash=hashlib.sha256(data).hexdigest(),
            object_key=entry.object_key,
            origin_run_id=run.id,
            origin="mirror",
            file_id=f"other-{entry.id}",
        )
    return conversation


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """A file-backed database with one org dashboard (USER) and one private one (OTHER_USER)."""
    monkeypatch.setattr("gateway.auth.notebook_jwt.load_session_jwt_secret", lambda: _TEST_SECRET)
    monkeypatch.setattr("gateway.auth.jwt_secret._cached_secret", _TEST_SECRET)
    monkeypatch.setattr("gateway.auth.user.is_cloud_mode", lambda: True)
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "1")
    storage, backend = fake_storage()
    monkeypatch.setattr(routes, "storage", lambda: storage)
    monkeypatch.setattr(publish_routes, "dashboard_storage", lambda: storage)
    monkeypatch.setattr(publish_routes, "governed_executor", FakeExecutor)

    async def _make():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'run-identity.sqlite'}")

        @event.listens_for(engine.sync_engine, "connect")
        def _fast_sqlite(connection, _record):
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA journal_mode=MEMORY")

        async with engine.begin() as connection:
            await connection.run_sync(GatewayBase.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with factory() as db:
            conversation, run, _rows = await add_conversation_with_files(db, backend)
            run.status = "running"
            await db.commit()
            mine = await publish_routes.publish_dashboard(
                conversation.id, "file-dash", publish_body(visibility="org"), api_store(db), "basic_member"
            )
            other_conversation = await _other_users_conversation(db, backend)
            theirs = await publish_routes.publish_dashboard(
                other_conversation.id,
                "other-file-dash",
                publish_body(name="Secret", visibility="private"),
                api_store(db, OTHER_USER),
                "basic_member",
            )
        return factory, run.id, conversation.id, mine, theirs

    factory, run_id, conversation_id, mine, theirs = asyncio.run(_make())

    from gateway.db.engine import get_db

    async def _db():
        async with factory() as session:
            yield session

    with isolated_app(monkeypatch, session_factory=factory) as app:
        app.dependency_overrides[get_db] = _db
        yield {
            "client": TestClient(app),
            "headers": {"Authorization": f"Bearer {_run_token(run_id)}"},
            "run_id": run_id,
            "conversation_id": conversation_id,
            "mine": mine["dashboard"],
            "mine_version": mine["version"],
            "theirs": theirs["dashboard"],
        }


class TestReadsWithTheRunToken:
    def test_list_applies_the_users_visibility(self, harness) -> None:
        response = harness["client"].get("/api/dashboards", headers=harness["headers"])
        assert response.status_code == 200, response.text
        listed = response.json()["dashboards"]
        assert [row["slug"] for row in listed] == ["revenue"]
        assert listed[0]["created_by_user_id"] == USER and listed[0]["can_edit"] is True

    def test_detail_by_slug_and_by_id(self, harness) -> None:
        client, headers = harness["client"], harness["headers"]
        by_slug = client.get("/api/dashboards/revenue", headers=headers)
        assert by_slug.status_code == 200, by_slug.text
        assert by_slug.json()["dashboard"]["id"] == harness["mine"].id
        assert len(by_slug.json()["versions"]) == 1
        by_id = client.get(f"/api/dashboards/{harness['mine'].id}", headers=headers)
        assert by_id.status_code == 200 and by_id.json()["dashboard"]["slug"] == "revenue"

    def test_bundle_returns_spec_and_rows(self, harness) -> None:
        url = f"/api/dashboards/{harness['mine'].id}/versions/{harness['mine_version'].id}/bundle"
        response = harness["client"].get(url, headers=harness["headers"])
        assert response.status_code == 200, response.text
        bundle = response.json()
        assert bundle["spec"]["title"] == "Revenue"
        assert bundle["version"]["version_no"] == 1
        assert bundle["datasets"]["monthly"][0] == {"month": "2026-01-01", "revenue": 100}
        assert bundle["datasets"]["inline"] == [{"k": "a", "v": 1}]

    def test_another_users_private_dashboard_stays_hidden(self, harness) -> None:
        client, headers = harness["client"], harness["headers"]
        assert client.get(f"/api/dashboards/{harness['theirs'].id}", headers=headers).status_code == 404
        assert client.get("/api/dashboards/secret", headers=headers).status_code == 404

    def test_a_token_for_another_org_sees_nothing(self, harness) -> None:
        headers = {"Authorization": f"Bearer {_run_token(harness['run_id'], org_id='org-z')}"}
        response = harness["client"].get("/api/dashboards", headers=headers)
        assert response.status_code == 200 and response.json()["dashboards"] == []

    def test_a_token_without_the_read_scope_is_403(self, harness) -> None:
        headers = {"Authorization": f"Bearer {_run_token(harness['run_id'], scopes=['execute'])}"}
        assert harness["client"].get("/api/dashboards", headers=headers).status_code == 403


class TestWritesRefuseTheRunToken:
    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("PATCH", "/api/dashboards/{id}", {"name": "Renamed"}),
            ("POST", "/api/dashboards/{id}/refresh", None),
            ("POST", "/api/dashboards/{id}/versions/{vid}/restore", None),
            ("POST", "/api/dashboards/{id}/archive", None),
            ("POST", "/api/dashboards/{id}/unarchive", None),
            ("POST", "/api/dashboards/{id}/edit-chat", None),
            ("DELETE", "/api/dashboards/{id}", None),
        ],
    )
    def test_dashboard_write_routes_are_403(self, harness, method: str, path: str, body) -> None:
        url = path.format(id=harness["mine"].id, vid=harness["mine_version"].id)
        response = harness["client"].request(method, url, headers=harness["headers"], json=body)
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == REFUSED
        # The dashboard is untouched.
        detail = harness["client"].get("/api/dashboards/revenue", headers=harness["headers"]).json()["dashboard"]
        assert detail["name"] == "Revenue" and detail["archived_at"] is None

    def test_publish_from_the_owned_conversation_is_403(self, harness) -> None:
        url = f"/api/chat/conversations/{harness['conversation_id']}/files/file-dash/publish-dashboard"
        body = json.loads(publish_body(name="Again").model_dump_json())
        response = harness["client"].post(url, headers=harness["headers"], json=body)
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == REFUSED
