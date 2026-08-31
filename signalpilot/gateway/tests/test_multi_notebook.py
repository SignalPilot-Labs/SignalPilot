"""Multi-notebook support: store, resource, archives, and worker payloads.

A conversation can own several named notebooks. "analysis" is the default
and every legacy single-notebook path must keep working unchanged.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import (
    GatewayBase,
    GatewayChatConversation,
    GatewayChatConversationNotebook,
    GatewayChatRuntimeArchive,
    GatewayNotebookSession,
    GatewayWorkspaceProject,
)
from gateway.standalone_chat import notebook_resource
from gateway.standalone_chat.worker_events import _notebook_started_payload
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
    return await chat_store.create_conversation_with_run(
        db,
        org_id=ORG,
        user_id=USER,
        project=project,
        branch="main",
        message="What changed in revenue?",
        commit_sha="a" * 40,
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
    notebook_name: str | None = None,
    created_at: datetime | None = None,
) -> GatewayChatRuntimeArchive:
    return GatewayChatRuntimeArchive(
        id=archive_id,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=UTC),
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation_id,
        run_id=run_id,
        notebook_name=notebook_name,
        source_object_key=source_key,
        html_object_key=f"{archive_id}/analysis.html",
        manifest_object_key=f"{archive_id}/manifest.json",
        source_hash=hashlib.sha256(source).hexdigest(),
        html_hash="0" * 64,
        manifest_hash="0" * 64,
    )


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    async def get_bytes(self, key: str, max_bytes: int) -> bytes:
        return self.objects[key]


# ── Store: named notebook pointers ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_is_latest_wins_and_list_orders_analysis_first(db_session):
    conversation, _run = await _conversation_and_run(db_session)
    for name, kernel in (("zeta", "s_z"), ("analysis", "s_a"), ("beta", "s_b")):
        await chat_store.upsert_conversation_notebook(
            db_session,
            conversation_id=conversation.id,
            name=name,
            gateway_session_id="gw-1",
            kernel_session_id=kernel,
            notebook_path=f"/scratch/{name}.py",
        )
    await chat_store.upsert_conversation_notebook(
        db_session,
        conversation_id=conversation.id,
        name="beta",
        gateway_session_id="gw-2",
        kernel_session_id="s_b2",
        notebook_path="/scratch/beta.py",
    )
    rows = await chat_store.list_conversation_notebooks(
        db_session, conversation_id=conversation.id
    )
    assert [row.name for row in rows] == ["analysis", "beta", "zeta"]
    beta = rows[1]
    assert beta.gateway_session_id == "gw-2"
    assert beta.kernel_session_id == "s_b2"


@pytest.mark.asyncio
async def test_set_pointer_for_run_mirrors_only_the_analysis_notebook(db_session):
    conversation, run = await _conversation_and_run(db_session)
    await chat_store.set_conversation_notebook_for_run(
        db_session,
        run_id=run.id,
        gateway_session_id="gw-1",
        kernel_session_id="s_rev",
        notebook_path="/scratch/revenue.py",
        name="revenue",
    )
    row = (
        await db_session.execute(
            select(GatewayChatConversation).where(
                GatewayChatConversation.id == conversation.id
            )
        )
    ).scalar_one()
    assert row.notebook_session_id is None
    await chat_store.set_conversation_notebook_for_run(
        db_session,
        run_id=run.id,
        gateway_session_id="gw-1",
        kernel_session_id="s_ana",
        notebook_path="/scratch/analysis.py",
    )
    await db_session.refresh(row)
    assert row.notebook_session_id == "gw-1"
    assert row.notebook_kernel_session_id == "s_ana"
    names = [
        r.name
        for r in await chat_store.list_conversation_notebooks(
            db_session, conversation_id=conversation.id
        )
    ]
    assert names == ["analysis", "revenue"]


# ── Resource: multi-notebook listing and legacy fallback ─────────────────────


@pytest.mark.asyncio
async def test_legacy_conversation_without_child_rows_yields_one_analysis_entry(
    db_session, monkeypatch
):
    conversation, _run = await _conversation_and_run(db_session)
    # Legacy shape: pointer columns only, no child-table rows.
    conversation.notebook_session_id = "gw-legacy"
    conversation.notebook_kernel_session_id = "s_old"
    conversation.notebook_path = "/scratch/analysis.py"
    await db_session.commit()
    monkeypatch.setattr(
        notebook_resource, "chat_object_storage", lambda: _FakeStorage({})
    )
    infos = await notebook_resource.get_conversation_notebooks(
        db_session,
        conversation=conversation,
        http_client=_http_client(lambda request: httpx.Response(500)),
    )
    assert len(infos) == 1
    assert infos[0].name == "analysis"
    assert infos[0].status == "ended"
    assert infos[0].kernel_session_id == "s_old"
    single = await notebook_resource.get_conversation_notebook(
        db_session,
        conversation=conversation,
        http_client=_http_client(lambda request: httpx.Response(500)),
    )
    assert single.name == "analysis"
    assert single.kernel_session_id == "s_old"


@pytest.mark.asyncio
async def test_shared_gateway_session_is_probed_once(db_session, monkeypatch):
    conversation, run = await _conversation_and_run(db_session)
    db_session.add(
        GatewayNotebookSession(
            id="gw-shared",
            org_id=ORG,
            user_id="chat:conv-x",
            status="running",
            backend="vercel",
            upstream_url="https://sandbox.example",
            created_at=1.0,
        )
    )
    await db_session.commit()
    for name in ("analysis", "revenue"):
        await chat_store.set_conversation_notebook_for_run(
            db_session,
            run_id=run.id,
            gateway_session_id="gw-shared",
            kernel_session_id=f"s_{name}",
            notebook_path=f"/scratch/{name}.py",
            name=name,
        )
    monkeypatch.setattr(
        notebook_resource, "chat_object_storage", lambda: _FakeStorage({})
    )
    probes: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        probes.append(str(request.url))
        return httpx.Response(200)

    infos = await notebook_resource.get_conversation_notebooks(
        db_session,
        conversation=conversation,
        http_client=_http_client(handler),
    )
    assert [info.name for info in infos] == ["analysis", "revenue"]
    assert all(info.status == "live" for info in infos)
    assert len(probes) == 1


# ── Resource: document selection by notebook name ────────────────────────────


@pytest.mark.asyncio
async def test_documents_are_selected_per_notebook_and_null_means_analysis(
    db_session, monkeypatch
):
    conversation, run = await _conversation_and_run(db_session)
    legacy = b"print('legacy analysis')\n"
    revenue = b"print('revenue')\n"
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="archive-legacy",
            source_key="legacy/analysis.py",
            source=legacy,
            notebook_name=None,
        )
    )
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="archive-revenue",
            source_key="rev/analysis.py",
            source=revenue,
            notebook_name="revenue",
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    await db_session.commit()
    monkeypatch.setattr(
        notebook_resource,
        "chat_object_storage",
        lambda: _FakeStorage(
            {"legacy/analysis.py": legacy, "rev/analysis.py": revenue}
        ),
    )
    analysis_doc = await notebook_resource._latest_document(
        db_session,
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        name="analysis",
    )
    revenue_doc = await notebook_resource._latest_document(
        db_session,
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        name="revenue",
    )
    other_doc = await notebook_resource._latest_document(
        db_session,
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        name="other",
    )
    assert analysis_doc is not None and "legacy" in analysis_doc.source
    assert revenue_doc is not None and "revenue" in revenue_doc.source
    assert other_doc is None


# ── Archives: one archive per (run, notebook) ────────────────────────────────


@pytest.mark.asyncio
async def test_archive_identity_is_unique_per_run_and_notebook(db_session):
    conversation, run = await _conversation_and_run(db_session)
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="a1",
            source_key="a1/analysis.py",
            source=b"one",
            notebook_name="analysis",
        )
    )
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="a2",
            source_key="a2/analysis.py",
            source=b"two",
            notebook_name="revenue",
        )
    )
    await db_session.commit()
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="a3",
            source_key="a3/analysis.py",
            source=b"three",
            notebook_name="revenue",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ── Worker: notebook name in the notebook_started payload ────────────────────


class TestNotebookStartedPayloadName:
    def test_extracts_the_notebook_name_from_json(self):
        payload = _notebook_started_payload(
            tool_result_content=json.dumps(
                {
                    "session_id": "s_abc",
                    "notebook": "revenue",
                    "notebook_path": "/tmp/signalpilot-chat-runs/revenue.py",
                }
            ),
            gateway_session_id="gw-1",
        )
        assert payload["notebook"] == "revenue"
        assert payload["kernel_session_id"] == "s_abc"

    def test_defaults_to_analysis_when_absent(self):
        payload = _notebook_started_payload(
            tool_result_content=json.dumps({"session_id": "s_abc"}),
            gateway_session_id="gw-1",
        )
        assert payload["notebook"] == "analysis"

    def test_extracts_the_notebook_name_from_content_block_repr(self):
        wrapped = (
            '[TextContent(type=\'text\', text=\'{"session_id": "s_abc123", '
            '"notebook": "revenue", '
            '"notebook_path": "/tmp/signalpilot-chat-runs/revenue.py"}\')]'
        )
        payload = _notebook_started_payload(
            tool_result_content=wrapped,
            gateway_session_id="gw-1",
        )
        assert payload["notebook"] == "revenue"
        assert payload["kernel_session_id"] == "s_abc123"
        assert payload["notebook_path"] == "/tmp/signalpilot-chat-runs/revenue.py"


class TestNotebookStartedPayloadAdversarial:
    def test_extracts_from_dict_shaped_block_repr(self):
        # str(block.content) when the SDK delivers MCP content as a list of
        # dicts (claude_agent.py builds tool_result content exactly this way).
        started = {
            "session_id": "s_r1",
            "status": "started",
            "cell_ids": ["MJUe", "vblA"],
            "notebook_path": "/tmp/signalpilot-chat-runs/run-1/report.py",
            "notebook": "report",
        }
        wrapped = str([{"type": "text", "text": json.dumps(started)}])
        payload = _notebook_started_payload(
            tool_result_content=wrapped,
            gateway_session_id="gw-1",
        )
        assert payload["kernel_session_id"] == "s_r1"
        assert payload["notebook"] == "report"
        assert payload["notebook_path"] == "/tmp/signalpilot-chat-runs/run-1/report.py"

    def test_extracts_from_escaped_json_inside_repr(self):
        # One extra escaping level: the JSON survives as \"key\": \"value\".
        wrapped = (
            "[{'type': 'text', 'text': '{\\\"session_id\\\": \\\"s_r2\\\", "
            "\\\"notebook\\\": \\\"report\\\"}'}]"
        )
        payload = _notebook_started_payload(
            tool_result_content=wrapped,
            gateway_session_id="gw-1",
        )
        assert payload["kernel_session_id"] == "s_r2"
        assert payload["notebook"] == "report"

    def test_survives_the_sdk_5000_char_truncation(self):
        # claude_agent.py truncates tool_result content to 5000 chars; the
        # leading ids must still be recovered from the broken JSON.
        started = {
            "session_id": "s_r3",
            "notebook": "report",
            "notebook_path": "/tmp/signalpilot-chat-runs/run-1/report.py",
            "cell_ids": ["c" * 6000],
        }
        wrapped = str([{"type": "text", "text": json.dumps(started)}])[:5000]
        payload = _notebook_started_payload(
            tool_result_content=wrapped,
            gateway_session_id="gw-1",
        )
        assert payload["kernel_session_id"] == "s_r3"
        assert payload["notebook"] == "report"


@pytest.mark.asyncio
async def test_null_named_archive_never_shadows_a_named_notebook(
    db_session, monkeypatch
):
    """A NEWER legacy NULL archive must stay out of a named notebook's
    document while still serving as the analysis document."""
    conversation, run = await _conversation_and_run(db_session)
    legacy = b"print('legacy analysis')\n"
    report = b"print('report')\n"
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="archive-report",
            source_key="rep/analysis.py",
            source=report,
            notebook_name="report",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    db_session.add(
        _archive(
            conversation.id,
            run.id,
            archive_id="archive-legacy-new",
            source_key="legacy/analysis.py",
            source=legacy,
            notebook_name=None,
            created_at=datetime(2026, 1, 5, tzinfo=UTC),
        )
    )
    await db_session.commit()
    monkeypatch.setattr(
        notebook_resource,
        "chat_object_storage",
        lambda: _FakeStorage(
            {"legacy/analysis.py": legacy, "rep/analysis.py": report}
        ),
    )
    report_doc = await notebook_resource._latest_document(
        db_session,
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        name="report",
    )
    analysis_doc = await notebook_resource._latest_document(
        db_session,
        org_id=ORG,
        user_id=USER,
        conversation_id=conversation.id,
        name="analysis",
    )
    assert report_doc is not None and "report" in report_doc.source
    assert analysis_doc is not None and "legacy" in analysis_doc.source


@pytest.mark.asyncio
async def test_gateway_rejects_malformed_sandbox_notebook_names(db_session):
    """The gateway trust boundary slug-validates the notebook name from
    sandbox output before persisting it. A malformed name means a corrupted
    payload and must never create a pointer row."""
    conversation, run = await _conversation_and_run(db_session)
    for hostile in ("../EVIL name\\x", "UPPER", "a" * 60, "-lead", ""):
        await chat_store.set_conversation_notebook_for_run(
            db_session,
            run_id=run.id,
            gateway_session_id="gw-1",
            kernel_session_id="s_evil",
            notebook_path="/scratch/../evil.py",
            name=hostile,
        )
    rows = await chat_store.list_conversation_notebooks(
        db_session, conversation_id=conversation.id
    )
    assert rows == []


@pytest.mark.asyncio
async def test_announce_notebook_forwards_the_notebook_name(monkeypatch):
    from gateway.standalone_chat import worker

    persisted: list[dict] = []

    async def fake_append(run_id, event_type, payload):
        return None

    async def fake_set(db, **kwargs):
        persisted.append(kwargs)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

    monkeypatch.setattr(worker, "_append", fake_append)
    monkeypatch.setattr(worker, "get_session_factory", lambda: FakeSession)
    monkeypatch.setattr(
        worker.chat_store, "set_conversation_notebook_for_run", fake_set
    )
    await worker._announce_notebook(
        "run-1",
        {
            "status": "running",
            "gateway_session_id": "gw-1",
            "kernel_session_id": "s_rev",
            "notebook_path": "/tmp/signalpilot-chat-runs/revenue.py",
            "notebook": "revenue",
        },
    )
    assert persisted and persisted[0]["name"] == "revenue"
    await worker._announce_notebook(
        "run-1",
        {
            "status": "running",
            "gateway_session_id": "gw-1",
            "kernel_session_id": "s_a",
            "notebook_path": "/tmp/signalpilot-chat-runs/analysis.py",
        },
    )
    assert persisted[1]["name"] == "analysis"
