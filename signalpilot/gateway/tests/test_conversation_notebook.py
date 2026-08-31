"""Contracts for the conversation notebook resource.

The resource is the single source of truth for the chat notebook panel:
where the notebook lives, whether its kernel is alive, and the newest saved
document. Liveness is probed and reconciled here, never trusted from the
session row.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import (
    GatewayBase,
    GatewayChatConversation,
    GatewayChatRuntimeArchive,
    GatewayNotebookSession,
    GatewayWorkspaceProject,
)
from gateway.standalone_chat import notebook_resource
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


async def _conversation_and_run(db: AsyncSession):
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


def _notebook_session(session_id: str, *, status: str = "running") -> GatewayNotebookSession:
    return GatewayNotebookSession(
        id=session_id,
        org_id=ORG,
        user_id="chat:conv-x",
        status=status,
        backend="vercel",
        upstream_url="https://sandbox.example",
        created_at=1.0,
    )


def _http_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _archive(
    conversation_id: str,
    run_id: str,
    *,
    archive_id: str,
    source_key: str,
    source: bytes,
    session_key: str | None = None,
    session_bytes: bytes | None = None,
    created_at: datetime | None = None,
) -> GatewayChatRuntimeArchive:
    return GatewayChatRuntimeArchive(
        id=archive_id,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation_id,
        run_id=run_id,
        source_object_key=source_key,
        html_object_key=f"{archive_id}/analysis.html",
        manifest_object_key=f"{archive_id}/manifest.json",
        session_object_key=session_key,
        source_hash=hashlib.sha256(source).hexdigest(),
        html_hash="0" * 64,
        manifest_hash="0" * 64,
        session_hash=(
            hashlib.sha256(session_bytes).hexdigest() if session_bytes else None
        ),
    )


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    async def get_bytes(self, key: str, max_bytes: int) -> bytes:
        return self.objects[key]


# ── Store: conversation notebook pointer ─────────────────────────────────────


@pytest.mark.asyncio
async def test_pointer_persists_for_a_run_and_the_newest_write_wins(db_session):
    conversation, run = await _conversation_and_run(db_session)
    await chat_store.set_conversation_notebook_for_run(
        db_session,
        run_id=run.id,
        gateway_session_id="gw-1",
        kernel_session_id="s_aaa",
        notebook_path="/scratch/analysis.py",
    )
    await chat_store.set_conversation_notebook_for_run(
        db_session,
        run_id=run.id,
        gateway_session_id="gw-1",
        kernel_session_id="s_bbb",
        notebook_path="/scratch/analysis.py",
    )
    row = (
        await db_session.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == conversation.id
            )
        )
    ).scalar_one()
    assert row.notebook_session_id == "gw-1"
    assert row.notebook_kernel_session_id == "s_bbb"
    assert row.notebook_path == "/scratch/analysis.py"


@pytest.mark.asyncio
async def test_pointer_write_for_an_unknown_run_is_a_no_op(db_session):
    await chat_store.set_conversation_notebook_for_run(
        db_session,
        run_id="missing-run",
        gateway_session_id="gw-1",
        kernel_session_id="s_aaa",
        notebook_path="/scratch/analysis.py",
    )


# ── Resource: status and liveness reconciliation ─────────────────────────────


@pytest.mark.asyncio
async def test_status_none_without_pointer_or_archive(db_session, monkeypatch):
    conversation, _run = await _conversation_and_run(db_session)
    monkeypatch.setattr(
        notebook_resource, "chat_object_storage", lambda: _FakeStorage({})
    )
    info = await notebook_resource.get_conversation_notebook(
        db_session,
        conversation=conversation,
        http_client=_http_client(lambda request: httpx.Response(500)),
    )
    assert info.status == "none"
    assert info.document is None


@pytest.mark.asyncio
async def test_live_when_the_sandbox_answers_its_health_probe(db_session, monkeypatch):
    conversation, run = await _conversation_and_run(db_session)
    db_session.add(_notebook_session("gw-live"))
    await db_session.commit()
    await chat_store.set_conversation_notebook_for_run(
        db_session,
        run_id=run.id,
        gateway_session_id="gw-live",
        kernel_session_id="s_aaa",
        notebook_path="/scratch/analysis.py",
    )
    conversation = await chat_store.get_owned_conversation(
        db_session, org_id=ORG, user_id=USER, conversation_id=conversation.id
    )
    monkeypatch.setattr(
        notebook_resource, "chat_object_storage", lambda: _FakeStorage({})
    )

    probed_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        probed_urls.append(str(request.url))
        return httpx.Response(200)

    info = await notebook_resource.get_conversation_notebook(
        db_session,
        conversation=conversation,
        http_client=_http_client(handler),
    )
    assert info.status == "live"
    assert info.gateway_session_id == "gw-live"
    assert info.kernel_session_id == "s_aaa"
    assert info.notebook_path == "/scratch/analysis.py"
    assert probed_urls == ["https://sandbox.example/notebook/gw-live/health"]


@pytest.mark.asyncio
async def test_dead_sandbox_is_reconciled_to_stopped(db_session, monkeypatch):
    conversation, run = await _conversation_and_run(db_session)
    db_session.add(_notebook_session("gw-dead"))
    await db_session.commit()
    await chat_store.set_conversation_notebook_for_run(
        db_session,
        run_id=run.id,
        gateway_session_id="gw-dead",
        kernel_session_id="s_aaa",
        notebook_path="/scratch/analysis.py",
    )
    conversation = await chat_store.get_owned_conversation(
        db_session, org_id=ORG, user_id=USER, conversation_id=conversation.id
    )
    monkeypatch.setattr(
        notebook_resource, "chat_object_storage", lambda: _FakeStorage({})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sandbox is gone")

    info = await notebook_resource.get_conversation_notebook(
        db_session,
        conversation=conversation,
        http_client=_http_client(handler),
    )
    assert info.status == "ended"
    row = (
        await db_session.execute(
            select(GatewayNotebookSession).where(GatewayNotebookSession.id == "gw-dead")
        )
    ).scalar_one()
    assert row.status == "stopped"


@pytest.mark.asyncio
async def test_stopped_session_is_not_probed(db_session, monkeypatch):
    conversation, run = await _conversation_and_run(db_session)
    db_session.add(_notebook_session("gw-stopped", status="stopped"))
    await db_session.commit()
    await chat_store.set_conversation_notebook_for_run(
        db_session,
        run_id=run.id,
        gateway_session_id="gw-stopped",
        kernel_session_id="s_aaa",
        notebook_path="/scratch/analysis.py",
    )
    conversation = await chat_store.get_owned_conversation(
        db_session, org_id=ORG, user_id=USER, conversation_id=conversation.id
    )
    monkeypatch.setattr(
        notebook_resource, "chat_object_storage", lambda: _FakeStorage({})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a stopped session must not be probed")

    info = await notebook_resource.get_conversation_notebook(
        db_session,
        conversation=conversation,
        http_client=_http_client(handler),
    )
    assert info.status == "ended"


# ── Resource: archived document selection ────────────────────────────────────


@pytest.mark.asyncio
async def test_newest_intact_archive_wins_and_includes_the_outputs_snapshot(
    db_session, monkeypatch
):
    conversation, run = await _conversation_and_run(db_session)
    old_source = b"print('old')\n"
    new_source = b"print('new')\n"
    snapshot = json.dumps({"version": "1", "metadata": {}, "cells": []}).encode()
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="archive-old",
            source_key="old/analysis.py",
            source=old_source,
        )
    )
    db_session.add(
        _archive(
            conversation.id,
            "run-2",
            archive_id="archive-new",
            source_key="new/analysis.py",
            source=new_source,
            session_key="new/session.json",
            session_bytes=snapshot,
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    await db_session.commit()
    monkeypatch.setattr(
        notebook_resource,
        "chat_object_storage",
        lambda: _FakeStorage(
            {
                "old/analysis.py": old_source,
                "new/analysis.py": new_source,
                "new/session.json": snapshot,
            }
        ),
    )
    info = await notebook_resource.get_conversation_notebook(
        db_session,
        conversation=conversation,
        http_client=_http_client(lambda request: httpx.Response(500)),
    )
    assert info.status == "ended"
    assert info.document is not None
    assert info.document.source == "print('new')\n"
    assert info.document.session == {"version": "1", "metadata": {}, "cells": []}


@pytest.mark.asyncio
async def test_a_broken_newest_archive_falls_back_to_an_older_one(
    db_session, monkeypatch
):
    conversation, run = await _conversation_and_run(db_session)
    old_source = b"print('old')\n"
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="archive-old",
            source_key="old/analysis.py",
            source=old_source,
        )
    )
    corrupt = _archive(
        conversation.id,
        "run-2",
        archive_id="archive-new",
        source_key="new/analysis.py",
        source=b"the stored bytes will not match this hash",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    db_session.add(corrupt)
    await db_session.commit()
    monkeypatch.setattr(
        notebook_resource,
        "chat_object_storage",
        lambda: _FakeStorage(
            {
                "old/analysis.py": old_source,
                "new/analysis.py": b"tampered",
            }
        ),
    )
    info = await notebook_resource.get_conversation_notebook(
        db_session,
        conversation=conversation,
        http_client=_http_client(lambda request: httpx.Response(500)),
    )
    assert info.document is not None
    assert info.document.source == "print('old')\n"


@pytest.mark.asyncio
async def test_other_users_archives_are_never_selected(db_session, monkeypatch):
    conversation, run = await _conversation_and_run(db_session)
    foreign = _archive(
        conversation.id,
        run.id,
        archive_id="archive-foreign",
        source_key="foreign/analysis.py",
        source=b"secret",
    )
    foreign.user_id = "user-b"
    db_session.add(foreign)
    await db_session.commit()
    monkeypatch.setattr(
        notebook_resource,
        "chat_object_storage",
        lambda: _FakeStorage({"foreign/analysis.py": b"secret"}),
    )
    info = await notebook_resource.get_conversation_notebook(
        db_session,
        conversation=conversation,
        http_client=_http_client(lambda request: httpx.Response(500)),
    )
    assert info.document is None
    assert info.status == "none"


# ── Worker: pointer announcement ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_announce_notebook_skips_partial_payloads(monkeypatch):
    from gateway.standalone_chat import worker

    appended: list[tuple[str, dict]] = []
    persisted: list[dict] = []

    async def fake_append(run_id, event_type, payload):
        appended.append((event_type, payload))

    async def fake_set(db, **kwargs):
        persisted.append(kwargs)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(worker, "_append", fake_append)
    monkeypatch.setattr(worker, "get_session_factory", lambda: FakeSession)
    monkeypatch.setattr(worker.chat_store, "set_conversation_notebook_for_run", fake_set)

    await worker._announce_notebook("run-1", {"status": "running"})
    assert appended == [("notebook_started", {"status": "running"})]
    assert persisted == []

    complete = {
        "status": "running",
        "gateway_session_id": "gw-1",
        "kernel_session_id": "s_aaa",
        "notebook_path": "/scratch/analysis.py",
    }
    await worker._announce_notebook("run-1", complete)
    assert persisted and persisted[0]["kernel_session_id"] == "s_aaa"


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner
