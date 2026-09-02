"""Conversation files: manifest store, content routes, and SQL trace.

The gateway is the single source of truth for the artifacts panel. These
tests cover kind derivation, latest-wins upserts, owner isolation, the
hash-verified content route with HTML sanitization, and the SQL trace
projection joined to query plans.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.chat_routes import files as files_routes
from gateway.db.models import (
    GatewayBase,
    GatewayChatFile,
    GatewayGovernedQueryExecution,
    GatewayQueryPlan,
    GatewayWorkspaceProject,
)
from gateway.standalone_chat.object_storage import conversation_file_key, conversation_prefix
from gateway.standalone_chat.sql_trace import list_sql_trace
from gateway.store import standalone_chat as chat_store

ORG = "org-a"
USER = "user-a"


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _conversation(db: AsyncSession):
    project = GatewayWorkspaceProject(
        id="project-a",
        org_id=ORG,
        name="revenue",
        display_name="Revenue",
        description="Revenue analytics",
        connection_name="production",
        source="managed",
        status="active",
        settings={},
        file_count=1,
        total_bytes=10,
        default_branch="main",
        created_at=1.0,
        updated_at=1.0,
    )
    db.add(project)
    await db.commit()
    conversation, _run = await chat_store.create_conversation_with_run(
        db,
        org_id=ORG,
        user_id=USER,
        project=project,
        branch="main",
        message="What changed in revenue?",
        commit_sha="a" * 40,
    )
    return conversation


async def _upsert(db: AsyncSession, conversation_id: str, path: str, data: bytes, **overrides):
    filename = path.rsplit("/", 1)[-1]
    kwargs = {
        "org_id": ORG,
        "user_id": USER,
        "conversation_id": conversation_id,
        "path": path,
        "filename": filename,
        "mime_type": None,
        "byte_size": len(data),
        "content_hash": hashlib.sha256(data).hexdigest(),
        "object_key": f"objects/{filename}",
        "origin_run_id": "run-1",
        "origin": "mirror",
    }
    kwargs.update(overrides)
    return await chat_store.upsert_conversation_file(db, **kwargs)


def _store(db: AsyncSession, user_id: str = USER):
    return SimpleNamespace(session=db, user_id=user_id, _require_org_id=lambda: ORG)


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
        return self.objects[key]


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "1")


# ── Kind derivation ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("filename", "mime_type", "expected"),
    [
        ("spec.md", None, "markdown"),
        ("notes.markdown", None, "markdown"),
        ("load.py", None, "code"),
        ("model.sql", None, "code"),
        ("app.ts", None, "code"),
        ("run.sh", None, "code"),
        ("conf.yaml", None, "code"),
        ("conf.toml", None, "code"),
        ("data.json", None, "code"),
        ("report.html", None, "html"),
        ("index.htm", None, "html"),
        ("chart.PNG", None, "image"),
        ("photo.jpeg", None, "image"),
        ("logo.svg", None, "image"),
        ("analysis.ipynb", None, "notebook"),
        ("rows.csv", None, "data"),
        ("rows.parquet", None, "data"),
        ("events.jsonl", None, "data"),
        ("blob.bin", None, "other"),
        ("noext", "image/png", "image"),
        ("noext", "text/html; charset=utf-8", "html"),
        ("noext", "text/markdown", "markdown"),
        ("noext", None, "other"),
    ],
)
def test_derive_file_kind(filename, mime_type, expected):
    assert chat_store.derive_file_kind(filename, mime_type) == expected


# ── Object key ───────────────────────────────────────────────────────────────


def test_conversation_file_key_is_under_the_conversation_prefix():
    key = conversation_file_key(
        org_id=ORG,
        conversation_id="conv-1",
        file_id="file-1",
        filename="my spec!.md",
    )
    assert key.startswith(f"{conversation_prefix(ORG, 'conv-1')}/files/")
    assert key.endswith("/file-1-my-spec-.md")


# ── Store: upsert, list, delete ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_latest_wins_and_reactivates(db_session):
    conversation = await _conversation(db_session)
    first = await _upsert(db_session, conversation.id, "artifacts/spec.md", b"v1")
    assert first.kind == "markdown"
    assert first.status == "active"

    deleted = await chat_store.mark_conversation_file_deleted(
        db_session,
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        path="artifacts/spec.md",
    )
    assert deleted is True
    assert (
        await chat_store.mark_conversation_file_deleted(
            db_session,
            org_id=ORG,
            user_id=USER,
            conversation_id=conversation.id,
            path="artifacts/spec.md",
        )
        is False
    )

    second = await _upsert(
        db_session,
        conversation.id,
        "artifacts/spec.md",
        b"v2",
        origin_run_id="run-2",
        origin="sweep",
    )
    assert second.id == first.id
    assert second.status == "active"
    assert second.origin == "sweep"
    assert second.origin_run_id == "run-2"
    assert second.content_hash == hashlib.sha256(b"v2").hexdigest()


@pytest.mark.asyncio
async def test_list_orders_by_newest_update_and_hides_deleted(db_session):
    conversation = await _conversation(db_session)
    older = await _upsert(db_session, conversation.id, "artifacts/a.md", b"a")
    newer = await _upsert(db_session, conversation.id, "artifacts/b.py", b"b")
    gone = await _upsert(db_session, conversation.id, "artifacts/c.csv", b"c")
    older.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    newer.updated_at = datetime(2026, 1, 2, tzinfo=UTC)
    gone.status = "deleted"
    await db_session.commit()

    rows = await chat_store.list_conversation_files(
        db_session, org_id=ORG, user_id=USER, conversation_id=conversation.id
    )
    assert [row.path for row in rows] == ["artifacts/b.py", "artifacts/a.md"]


@pytest.mark.asyncio
async def test_other_users_see_nothing(db_session):
    conversation = await _conversation(db_session)
    row = await _upsert(db_session, conversation.id, "artifacts/a.md", b"a")
    assert (
        await chat_store.list_conversation_files(
            db_session, org_id=ORG, user_id="user-b", conversation_id=conversation.id
        )
        == []
    )
    assert (
        await chat_store.get_conversation_file(
            db_session,
            org_id=ORG,
            user_id="user-b",
            conversation_id=conversation.id,
            file_id=row.id,
        )
        is None
    )


# ── Routes: manifest, content, isolation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_manifest_route_returns_file_info(db_session, enabled):
    conversation = await _conversation(db_session)
    await _upsert(db_session, conversation.id, "artifacts/spec.md", b"v1", mime_type="text/markdown")
    result = await files_routes.list_conversation_files(conversation.id, _store(db_session))
    assert len(result["files"]) == 1
    info = result["files"][0]
    assert info["path"] == "artifacts/spec.md"
    assert info["kind"] == "markdown"
    assert info["mime_type"] == "text/markdown"
    assert info["content_hash"] == hashlib.sha256(b"v1").hexdigest()
    assert set(info) == {
        "id",
        "path",
        "filename",
        "kind",
        "mime_type",
        "byte_size",
        "content_hash",
        "origin_run_id",
        "origin",
        "status",
        "created_at",
        "updated_at",
    }


@pytest.mark.asyncio
async def test_routes_404_for_a_foreign_conversation(db_session, enabled):
    conversation = await _conversation(db_session)
    store = _store(db_session, user_id="user-b")
    for call in (
        files_routes.list_conversation_files(conversation.id, store),
        files_routes.get_conversation_file_content(conversation.id, "file-x", store),
        files_routes.get_conversation_sql_trace(conversation.id, store),
    ):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_content_route_verifies_the_hash(db_session, enabled, monkeypatch):
    conversation = await _conversation(db_session)
    row = await _upsert(db_session, conversation.id, "artifacts/spec.md", b"hello")
    monkeypatch.setattr(
        files_routes, "chat_object_storage", lambda: _FakeStorage({row.object_key: b"hello"})
    )
    response = await files_routes.get_conversation_file_content(conversation.id, row.id, _store(db_session))
    assert response.body == b"hello"
    assert response.media_type == "application/octet-stream"
    assert response.headers["Cache-Control"] == "private, max-age=0, must-revalidate"
    assert response.headers["ETag"] == f'"{row.content_hash}"'
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Disposition" not in response.headers

    monkeypatch.setattr(
        files_routes, "chat_object_storage", lambda: _FakeStorage({row.object_key: b"tampered"})
    )
    with pytest.raises(HTTPException) as exc:
        await files_routes.get_conversation_file_content(conversation.id, row.id, _store(db_session))
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_html_content_is_sanitized_and_csp_pinned(db_session, enabled, monkeypatch):
    conversation = await _conversation(db_session)
    html = b'<html><head><base href="https://evil.example/"></head><body>ok</body></html>'
    row = await _upsert(
        db_session,
        conversation.id,
        "artifacts/report.html",
        html,
        mime_type="text/html",
    )
    monkeypatch.setattr(
        files_routes, "chat_object_storage", lambda: _FakeStorage({row.object_key: html})
    )
    response = await files_routes.get_conversation_file_content(
        conversation.id, row.id, _store(db_session), download=1
    )
    body = response.body.decode("utf-8")
    assert "<base" not in body
    assert "Content-Security-Policy" in body
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert response.headers["Content-Disposition"].startswith(
        'attachment; filename="report.html"'
    )
    assert response.media_type == "text/html"


# ── SQL trace projection ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sql_trace_joins_plans_and_orders_by_creation(db_session):
    conversation = await _conversation(db_session)
    plan = GatewayQueryPlan(
        id="plan-1",
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        connection_name="production",
        purpose="revenue by month",
        execution_need="full",
        normalized_sql="select 1",
        sql_hash="b" * 64,
        estimate_quality="exact",
        route="direct",
        route_reason="cheap",
        policy_version="v1",
        policy_hash="c" * 64,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    planned = GatewayGovernedQueryExecution(
        id="exec-1",
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        run_id="run-1",
        connection_name="production",
        plan_id="plan-1",
        query_path="direct",
        sql_hash="b" * 64,
        status="succeeded",
        timeout_seconds=60,
        actual_cost_usd=0.01,
        execution_ms=12.5,
        row_count=3,
        completeness="complete",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    planless = GatewayGovernedQueryExecution(
        id="exec-2",
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        connection_name="production",
        query_path="direct",
        sql_hash="d" * 64,
        status="failed",
        timeout_seconds=60,
        public_error_code="query_failed",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    foreign = GatewayGovernedQueryExecution(
        id="exec-3",
        org_id=ORG,
        user_id="user-b",
        conversation_id=conversation.id,
        connection_name="production",
        query_path="direct",
        sql_hash="e" * 64,
        status="succeeded",
        timeout_seconds=60,
        created_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    db_session.add_all([plan, planned, planless, foreign])
    await db_session.commit()

    rows = await list_sql_trace(
        db_session, org_id=ORG, user_id=USER, conversation_id=conversation.id
    )
    assert [row["execution_id"] for row in rows] == ["exec-1", "exec-2"]
    assert rows[0]["sql"] == "select 1"
    assert rows[0]["connection_name"] == "production"
    assert rows[0]["actual_cost_usd"] == 0.01
    assert rows[0]["row_count"] == 3
    assert rows[1]["sql"] is None
    assert rows[1]["public_error_code"] == "query_failed"
    assert set(rows[0]) == {
        "execution_id",
        "run_id",
        "connection_name",
        "sql",
        "sql_hash",
        "status",
        "query_path",
        "estimated_cost_usd",
        "actual_cost_usd",
        "actual_scan_bytes",
        "execution_ms",
        "row_count",
        "completeness",
        "public_error_code",
        "created_at",
        "started_at",
        "terminal_at",
    }


@pytest.mark.asyncio
async def test_sql_trace_route_wraps_the_projection(db_session, enabled):
    conversation = await _conversation(db_session)
    result = await files_routes.get_conversation_sql_trace(conversation.id, _store(db_session))
    assert result == {"executions": []}


# ── Adversarial: sanitization bypass and header safety ───────────────────────


@pytest.mark.asyncio
async def test_svg_content_is_forced_to_download(db_session, enabled, monkeypatch):
    """SVG can carry script when opened as a document. Serve it as an
    attachment even without the download flag."""
    conversation = await _conversation(db_session)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    row = await _upsert(
        db_session,
        conversation.id,
        "artifacts/logo.svg",
        svg,
        mime_type="image/svg+xml",
    )
    monkeypatch.setattr(
        files_routes,
        "chat_object_storage",
        lambda: _FakeStorage({row.object_key: svg}),
    )
    response = await files_routes.get_conversation_file_content(
        conversation.id, row.id, _store(db_session)
    )
    assert "attachment" in response.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_mirror_event_types_pass_response_model_validation():
    """A files event in the stream must never 500 the conversation detail."""
    from datetime import UTC, datetime

    from gateway.models.standalone_chat import ChatRunEventInfo

    for event_type in ("files_changed", "files_archived"):
        info = ChatRunEventInfo(
            run_id="run-1",
            sequence=1,
            type=event_type,
            payload={"changed": 1},
            created_at=datetime.now(UTC),
        )
        assert info.type == event_type


# ── ETag revalidation ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_if_none_match_returns_304_without_reading_the_object(db_session, enabled, monkeypatch):
    conversation = await _conversation(db_session)
    row = await _upsert(db_session, conversation.id, "artifacts/spec.md", b"hello")
    reads: list[str] = []

    class _CountingStorage(_FakeStorage):
        async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
            reads.append(key)
            return await super().get_bytes(key, max_bytes=max_bytes)

    monkeypatch.setattr(
        files_routes, "chat_object_storage", lambda: _CountingStorage({row.object_key: b"hello"})
    )
    etag = f'"{row.content_hash}"'
    for header in (etag, f"W/{etag}", f'"stale", {etag}', "*"):
        response = await files_routes.get_conversation_file_content(
            conversation.id, row.id, _store(db_session), if_none_match=header
        )
        assert response.status_code == 304
        assert response.body == b""
        assert response.headers["ETag"] == etag
        assert response.headers["Cache-Control"] == "private, max-age=0, must-revalidate"
    assert reads == []

    response = await files_routes.get_conversation_file_content(
        conversation.id, row.id, _store(db_session), if_none_match='"other"'
    )
    assert response.status_code == 200
    assert response.body == b"hello"
    assert reads == [row.object_key]


# ── Shared routes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shared_routes_require_the_sharing_flag_and_an_active_grant(
    db_session, enabled, monkeypatch
):
    conversation = await _conversation(db_session)
    row = await _upsert(db_session, conversation.id, "artifacts/spec.md", b"v1")
    monkeypatch.delenv("SP_FEATURE_CHAT_ORG_SHARING", raising=False)
    with pytest.raises(HTTPException) as exc:
        await files_routes.list_shared_conversation_files("x" * 40, _store(db_session, "user-b"))
    assert exc.value.status_code == 404

    monkeypatch.setenv("SP_FEATURE_CHAT_ORG_SHARING", "1")
    with pytest.raises(HTTPException) as exc:
        await files_routes.list_shared_conversation_files("x" * 40, _store(db_session, "user-b"))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await files_routes.get_shared_conversation_file_content(
            "x" * 40, row.id, _store(db_session, "user-b")
        )
    assert exc.value.status_code == 404

    shared = await chat_store.create_share_grant(
        db_session, org_id=ORG, user_id=USER, conversation_id=conversation.id
    )
    assert shared is not None
    _, token = shared
    # The seeded row points at run-1, which does not exist, so it is share-safe.
    listed = await files_routes.list_shared_conversation_files(token, _store(db_session, "user-b"))
    assert [item["id"] for item in listed["files"]] == [row.id]
    monkeypatch.setattr(
        files_routes, "chat_object_storage", lambda: _FakeStorage({row.object_key: b"v1"})
    )
    response = await files_routes.get_shared_conversation_file_content(
        token, row.id, _store(db_session, "user-b"), download=1
    )
    assert response.body == b"v1"
    assert response.headers["Cache-Control"] == "private, max-age=0, must-revalidate"
    assert response.headers["ETag"] == f'"{row.content_hash}"'
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Disposition"].startswith('attachment; filename="spec.md"')

    # Cross-org viewers see nothing.
    foreign = SimpleNamespace(session=db_session, user_id="user-b", _require_org_id=lambda: "org-b")
    with pytest.raises(HTTPException) as exc:
        await files_routes.list_shared_conversation_files(token, foreign)
    assert exc.value.status_code == 404

