"""Chat-scoped full-row access to structured query results.

Covers the row loader shared with the SDK route (inline vs object storage,
sha256 integrity) and the conversation-scoped route: owner paging with
offset/limit, ownership isolation across users and conversations, limit
clamping, and independence from the agent-facing structured_results flag.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api.chat_routes import query_results as results_routes
from gateway.db.models import GatewayBase, GatewayStructuredQueryResult, GatewayWorkspaceProject
from gateway.standalone_chat import query_results as loader
from gateway.standalone_chat.config import enterprise_chat_feature_flags
from gateway.store import standalone_chat as chat_store

ORG = "org-a"
USER = "user-a"
COLUMNS = [{"name": "id", "logical_type": "integer"}, {"name": "name", "logical_type": "string"}]


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "1")


async def _conversation(db: AsyncSession, *, project_id: str = "project-a"):
    project = await db.get(GatewayWorkspaceProject, project_id)
    if project is None:
        project = GatewayWorkspaceProject(
            id=project_id,
            org_id=ORG,
            name=project_id,
            display_name=project_id,
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
    conversation, run = await chat_store.create_conversation_with_run(
        db,
        org_id=ORG,
        user_id=USER,
        project=project,
        branch="main",
        message="What changed in revenue?",
        commit_sha="a" * 40,
    )
    return conversation, run


def _rows(count: int) -> list[dict]:
    return [{"id": index, "name": f"row-{index}"} for index in range(count)]


async def _result(db: AsyncSession, conversation, run, rows: list[dict], **overrides):
    kwargs = {
        "id": "res-1",
        "execution_id": "exec-1",
        "org_id": ORG,
        "owner_user_id": USER,
        "conversation_id": conversation.id,
        "run_id": run.id,
        "columns_json": COLUMNS,
        "rows_json": rows,
        "preview_rows_json": rows[:5],
        "storage_kind": "inline",
        "query_row_count": len(rows),
        "saved_row_count": len(rows),
        "source_completeness": "complete",
        "result_completeness": "complete",
        "display_completeness": "truncated",
        "truncation_reason": None,
        "provenance_json": {"connection_name": "production", "sql_hash": "b" * 64},
    }
    kwargs.update(overrides)
    stored = GatewayStructuredQueryResult(**kwargs)
    db.add(stored)
    await db.commit()
    return stored


def _store(db: AsyncSession, user_id: str = USER):
    return SimpleNamespace(session=db, user_id=user_id, _require_org_id=lambda: ORG)


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects
        self.calls: list[str] = []

    async def get_bytes(self, key: str, *, max_bytes: int | None = None) -> bytes:
        self.calls.append(key)
        return self.objects[key]


async def _get(db, conversation_id, result_id, *, user_id=USER, **params):
    return await results_routes.get_conversation_query_result(
        conversation_id, result_id, _store(db, user_id=user_id), **params
    )


# ── Loader ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loader_returns_inline_rows_without_touching_storage(monkeypatch):
    def _no_storage():
        raise AssertionError("inline results must not hit object storage")

    monkeypatch.setattr(loader, "chat_object_storage", _no_storage)
    stored = SimpleNamespace(storage_kind="inline", rows_json=_rows(3))
    assert await loader.load_result_rows(stored) == _rows(3)


@pytest.mark.asyncio
async def test_loader_verifies_object_hash(monkeypatch):
    data = json.dumps(_rows(4)).encode("utf-8")
    good = SimpleNamespace(
        storage_kind="object",
        rows_json=[],
        object_key="k",
        content_hash=hashlib.sha256(data).hexdigest(),
    )
    monkeypatch.setattr(loader, "chat_object_storage", lambda: _FakeStorage({"k": data}))
    assert await loader.load_result_rows(good) == _rows(4)

    monkeypatch.setattr(loader, "chat_object_storage", lambda: _FakeStorage({"k": b"[]"}))
    with pytest.raises(loader.QueryResultUnavailable):
        await loader.load_result_rows(good)

    with pytest.raises(loader.QueryResultUnavailable):
        await loader.load_result_rows(SimpleNamespace(storage_kind="object", rows_json=[], object_key=None))

    monkeypatch.setattr(loader, "chat_object_storage", lambda: _FakeStorage({"k": b'{"not": "a list"}'}))
    with pytest.raises(loader.QueryResultUnavailable):
        await loader.load_result_rows(SimpleNamespace(storage_kind="object", rows_json=[], object_key="k", content_hash=None))


# ── Route: owner paging ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_pages_rows_with_offset_and_limit(db_session, enabled):
    conversation, run = await _conversation(db_session)
    await _result(db_session, conversation, run, _rows(12))

    first = await _get(db_session, conversation.id, "res-1", offset=0, limit=5)
    assert [row["id"] for row in first["rows"]] == [0, 1, 2, 3, 4]
    assert first["offset"] == 0
    assert first["limit"] == 5
    assert first["result_id"] == "res-1"
    assert first["execution_id"] == "exec-1"
    assert first["columns"] == COLUMNS
    assert first["saved_row_count"] == 12
    assert first["query_row_count"] == 12
    assert first["completeness"] == "complete"
    assert first["truncation_reason"] is None
    assert first["connection_name"] == "production"
    assert set(first) == {
        "result_id",
        "execution_id",
        "columns",
        "rows",
        "offset",
        "limit",
        "saved_row_count",
        "query_row_count",
        "completeness",
        "truncation_reason",
        "connection_name",
    }

    second = await _get(db_session, conversation.id, "res-1", offset=10, limit=5)
    assert [row["id"] for row in second["rows"]] == [10, 11]
    assert second["offset"] == 10

    beyond = await _get(db_session, conversation.id, "res-1", offset=50, limit=5)
    assert beyond["rows"] == []


@pytest.mark.asyncio
async def test_default_page_is_500_rows(db_session, enabled):
    conversation, run = await _conversation(db_session)
    await _result(db_session, conversation, run, _rows(700))
    page = await _get(db_session, conversation.id, "res-1")
    assert len(page["rows"]) == 500
    assert page["limit"] == 500
    assert page["offset"] == 0


@pytest.mark.asyncio
async def test_limit_and_offset_are_clamped(db_session, enabled):
    conversation, run = await _conversation(db_session)
    await _result(db_session, conversation, run, _rows(1500))

    page = await _get(db_session, conversation.id, "res-1", limit=5000)
    assert page["limit"] == 1000
    assert len(page["rows"]) == 1000

    page = await _get(db_session, conversation.id, "res-1", limit=0)
    assert page["limit"] == 1
    assert len(page["rows"]) == 1

    page = await _get(db_session, conversation.id, "res-1", offset=-7, limit=2)
    assert page["offset"] == 0
    assert [row["id"] for row in page["rows"]] == [0, 1]


@pytest.mark.asyncio
async def test_connection_name_is_null_without_provenance(db_session, enabled):
    conversation, run = await _conversation(db_session)
    await _result(db_session, conversation, run, _rows(1), provenance_json={})
    page = await _get(db_session, conversation.id, "res-1")
    assert page["connection_name"] is None


# ── Route: isolation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_other_user_gets_404(db_session, enabled):
    conversation, run = await _conversation(db_session)
    await _result(db_session, conversation, run, _rows(3))
    with pytest.raises(HTTPException) as exc:
        await _get(db_session, conversation.id, "res-1", user_id="user-b")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_result_from_another_conversation_gets_404(db_session, enabled):
    conversation, run = await _conversation(db_session)
    other, _other_run = await _conversation(db_session)
    assert other.id != conversation.id
    await _result(db_session, conversation, run, _rows(3))
    with pytest.raises(HTTPException) as exc:
        await _get(db_session, other.id, "res-1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_result_owned_by_another_user_in_same_conversation_gets_404(db_session, enabled):
    conversation, run = await _conversation(db_session)
    await _result(db_session, conversation, run, _rows(3), owner_user_id="user-b")
    with pytest.raises(HTTPException) as exc:
        await _get(db_session, conversation.id, "res-1")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unknown_result_gets_404(db_session, enabled):
    conversation, _run = await _conversation(db_session)
    with pytest.raises(HTTPException) as exc:
        await _get(db_session, conversation.id, "missing")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_disabled_chat_feature_gets_404(db_session, monkeypatch):
    monkeypatch.setenv("SP_FEATURE_STANDALONE_CHAT", "0")
    conversation, run = await _conversation(db_session)
    await _result(db_session, conversation, run, _rows(3))
    with pytest.raises(HTTPException) as exc:
        await _get(db_session, conversation.id, "res-1")
    assert exc.value.status_code == 404


# ── Route: object storage + flag independence ────────────────────────────────


@pytest.mark.asyncio
async def test_object_storage_kind_loads_through_the_shared_loader(db_session, enabled, monkeypatch):
    conversation, run = await _conversation(db_session)
    rows = _rows(30)
    data = json.dumps(rows).encode("utf-8")
    await _result(
        db_session,
        conversation,
        run,
        rows[:5],
        storage_kind="object",
        object_key="results/res-1/rows.json",
        content_hash=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        saved_row_count=30,
        query_row_count=30,
    )
    storage = _FakeStorage({"results/res-1/rows.json": data})
    monkeypatch.setattr(loader, "chat_object_storage", lambda: storage)

    page = await _get(db_session, conversation.id, "res-1", offset=20, limit=5)
    assert storage.calls == ["results/res-1/rows.json"]
    assert [row["id"] for row in page["rows"]] == [20, 21, 22, 23, 24]
    assert page["saved_row_count"] == 30

    tampered = _FakeStorage({"results/res-1/rows.json": b"[]"})
    monkeypatch.setattr(loader, "chat_object_storage", lambda: tampered)
    with pytest.raises(HTTPException) as exc:
        await _get(db_session, conversation.id, "res-1")
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_structured_results_flag_off_does_not_block(db_session, enabled, monkeypatch):
    monkeypatch.setenv("SP_FEATURE_CHAT_STRUCTURED_RESULTS", "0")
    assert enterprise_chat_feature_flags().structured_results is False
    conversation, run = await _conversation(db_session)
    await _result(db_session, conversation, run, _rows(3))
    page = await _get(db_session, conversation.id, "res-1")
    assert len(page["rows"]) == 3
