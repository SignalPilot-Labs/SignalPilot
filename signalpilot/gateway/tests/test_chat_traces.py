from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase
from gateway.models.workspace import ChatTraceEventCreate, ChatTraceThreadUpsert
from gateway.store.chat_traces import (
    append_event,
    clear_events,
    get_events,
    get_thread,
    list_threads,
    upsert_thread,
)


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def _thread(**overrides) -> ChatTraceThreadUpsert:
    data = {
        "thread_id": "thread-1",
        "session_id": "session-1",
        "source": "notion",
        "title": "Initial",
        "status": "active",
        "notebook_path": "analysis.py",
        "notion_request_page_id": "request-page",
        "notion_discussion_id": "discussion",
        "metadata": {"request_id": "request-1"},
    }
    data.update(overrides)
    return ChatTraceThreadUpsert(**data)


@pytest.mark.asyncio
async def test_trace_thread_upsert_updates_without_duplicate(db_session) -> None:
    await upsert_thread(
        db_session, org_id="org-a", user_id="user-a", thread=_thread()
    )
    await upsert_thread(
        db_session,
        org_id="org-a",
        user_id="user-a",
        thread=_thread(title="Updated", status="done", metadata=None),
    )

    threads = await list_threads(
        db_session, org_id="org-a", user_id="user-a", session_id="session-1"
    )

    assert len(threads) == 1
    assert threads[0].title == "Updated"
    assert threads[0].status == "done"
    assert threads[0].notion_request_page_id == "request-page"
    assert threads[0].metadata == {"request_id": "request-1"}


@pytest.mark.asyncio
async def test_append_events_monotonic_and_clear_scoped(db_session) -> None:
    await upsert_thread(
        db_session, org_id="org-a", user_id="user-a", thread=_thread()
    )
    await upsert_thread(
        db_session,
        org_id="org-a",
        user_id="user-a",
        thread=_thread(thread_id="thread-2", session_id="session-2"),
    )

    first_idx = await append_event(
        db_session,
        org_id="org-a",
        user_id="user-a",
        thread_id="thread-1",
        event=ChatTraceEventCreate(type="user", role="user", content="hello"),
    )
    second_idx = await append_event(
        db_session,
        org_id="org-a",
        user_id="user-a",
        thread_id="thread-1",
        event=ChatTraceEventCreate(
            type="tool_use",
            tool_name="Read",
            tool_input={"file_path": "analysis.py"},
            tool_call_id="tool-1",
        ),
    )
    other_idx = await append_event(
        db_session,
        org_id="org-a",
        user_id="user-a",
        thread_id="thread-2",
        event=ChatTraceEventCreate(type="text", content="other"),
    )

    assert (first_idx, second_idx, other_idx) == (0, 1, 0)

    events = await get_events(
        db_session,
        org_id="org-a",
        user_id="user-a",
        thread_id="thread-1",
        after_index=0,
    )
    assert [event.idx for event in events] == [1]
    assert events[0].tool_input == {"file_path": "analysis.py"}

    nullable_idx = await append_event(
        db_session,
        org_id="org-a",
        user_id="user-a",
        thread_id="thread-1",
        event=ChatTraceEventCreate(
            type="text",
            content=None,
            tool_name=None,
            tool_call_id=None,
            is_error=None,
            turn=None,
        ),
    )
    nullable_events = await get_events(
        db_session,
        org_id="org-a",
        user_id="user-a",
        thread_id="thread-1",
        after_index=1,
    )
    assert nullable_idx == 2
    assert nullable_events[0].content == ""
    assert nullable_events[0].tool_name == ""
    assert nullable_events[0].tool_call_id == ""
    assert nullable_events[0].is_error is False
    assert nullable_events[0].turn == 0

    assert await clear_events(
        db_session, org_id="org-a", user_id="user-a", thread_id="thread-1"
    )
    assert (
        await get_events(
            db_session,
            org_id="org-a",
            user_id="user-a",
            thread_id="thread-1",
        )
        == []
    )
    assert len(
        await get_events(
            db_session,
            org_id="org-a",
            user_id="user-a",
            thread_id="thread-2",
        )
    ) == 1


@pytest.mark.asyncio
async def test_trace_thread_listing_is_org_scoped(db_session) -> None:
    await upsert_thread(
        db_session, org_id="org-a", user_id="user-a", thread=_thread()
    )
    await upsert_thread(
        db_session,
        org_id="org-a",
        user_id="user-b",
        thread=_thread(thread_id="thread-user-b"),
    )
    await upsert_thread(
        db_session,
        org_id="org-b",
        user_id="user-a",
        thread=_thread(thread_id="thread-org-b"),
    )

    source_threads = await list_threads(
        db_session, org_id="org-a", user_id="user-a", source="notion"
    )

    assert {thread.thread_id for thread in source_threads} == {"thread-1", "thread-user-b"}
    assert (
        await get_thread(
            db_session,
            org_id="org-a",
            user_id="user-b",
            thread_id="thread-1",
        )
        is not None
    )
    assert (
        await get_thread(
            db_session,
            org_id="org-b",
            user_id="user-a",
            thread_id="thread-1",
        )
        is None
    )
    with pytest.raises(ValueError, match="not found"):
        await get_events(
            db_session,
            org_id="org-b",
            user_id="user-a",
            thread_id="thread-1",
        )
