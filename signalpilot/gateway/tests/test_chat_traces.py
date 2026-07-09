from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.db.models import GatewayBase
from gateway.models.workspace import ChatTraceEventCreate, ChatTraceThreadUpsert
from gateway.slack_poc.progress import (
    INITIAL_PROGRESS_TEXT,
    ProgressSummary,
    SlackProgressReporter,
    SlackProgressSummarizer,
    build_status_hints,
    extract_progress_objects,
    extract_progress_signals,
    sanitize_trace_events,
)
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


def test_slack_progress_sanitizer_extracts_signals_without_findings() -> None:
    events = [
        {
            "idx": 201,
            "type": "text",
            "content": "All 9 cells were added successfully. Now let me run all cells.",
            "created_at": 100.0,
        },
        {
            "idx": 202,
            "type": "tool_use",
            "tool_name": "mcp__signalpilot-notebook__edit_notebook",
            "tool_input": {
                "edits": [
                    {
                        "code": (
                            "import signalpilot as sp\n"
                            "db = sp.connect('fin-db')\n"
                            "result = db.query(\"SELECT SUM(total_revenue) FROM analytics_marts.fct_transfers\")"
                        )
                    }
                ]
            },
            "created_at": 101.0,
        },
        {
            "idx": 203,
            "type": "tool_use",
            "tool_name": "mcp__signalpilot-notebook__run_cells",
            "tool_input": {"session_id": "session-slack-99cf7447b23c57f7"},
            "created_at": 102.0,
        },
        {
            "idx": 204,
            "type": "text",
            "content": (
                '{"finalAnswer":"Revenue was 2,628.88 across 220 completed transfers",'
                '"confidenceScore":"high"}'
            ),
            "created_at": 103.0,
        },
        {
            "idx": 205,
            "type": "tool_result",
            "content": "Traceback (most recent call last): SELECT * FROM analytics_marts.fct_transfers",
            "created_at": 104.0,
        },
    ]

    signals = extract_progress_signals(events)
    sanitized = sanitize_trace_events(events, started_at=100.0)
    serialized = str(sanitized)

    assert "connects_to_fin-db" in signals
    assert "contains_db_query" in signals
    assert "uses_dbt_marts" in signals
    assert "runs_notebook_cells" in signals
    assert "fin-db" in serialized
    assert "analytics_marts.fct_transfers" in serialized
    assert "All 9 cells were added successfully" in serialized
    assert "2,628.88" not in serialized
    assert "220 completed" not in serialized
    assert "finalAnswer" not in serialized
    assert "SELECT SUM" not in serialized
    assert "Traceback" not in serialized


def test_slack_progress_extracts_safe_objects_for_ai_status() -> None:
    events = [
        {
            "type": "tool_use",
            "tool_name": "mcp__signalpilot-notebook__edit_notebook",
            "tool_input": {
                "code": (
                    "db = sp.connect('private-equity-db')\n"
                    "db.query('select * from staging.fct_revenue')\n"
                    "open('models/marts/fct_revenue.sql')"
                )
            },
        }
    ]

    assert extract_progress_objects(events) == [
        "private-equity-db",
        "staging.fct_revenue",
        "models/marts/fct_revenue.sql",
    ]
    assert extract_progress_objects(
        [
            {
                "type": "tool_use",
                "tool_name": "mcp__signalpilot-notebook__edit_notebook",
                "tool_input": {"code": 'db = sp.connect(\\"private-equity-db\\")'},
            }
        ]
    ) == ["private-equity-db"]


def test_slack_progress_extracts_chart_labels_and_status_hints() -> None:
    events = [
        {
            "idx": 164,
            "type": "tool_use",
            "tool_name": "mcp__signalpilot-notebook__edit_notebook",
            "tool_input": {
                "edits": [
                    {
                        "code": (
                            "def build_ebitda_chart(fin_df):\n"
                            "    ax_eb.set_title('Monthly EBITDA by Portfolio Company')\n"
                            "    fig_eb.savefig('/tmp/ebitda_trends.png')\n"
                            "ebitda_chart = build_ebitda_chart(financials_df)"
                        )
                    }
                ]
            },
        }
    ]
    sanitized = sanitize_trace_events(events)

    assert sanitized[0]["objects"] == [
        "ebitda chart",
        "Monthly EBITDA by Portfolio Company",
        "ebitda trends chart",
    ]
    assert build_status_hints(
        {
            "recentEvents": sanitized,
            "observedObjects": ["portfolio.monthly_financials", "ebitda chart"],
        }
    ) == ["Building Monthly EBITDA by Portfolio Company chart..."]


def test_slack_progress_sanitizes_notebook_error_results() -> None:
    sanitized = sanitize_trace_events(
        [
            {
                "idx": 88,
                "type": "tool_result",
                "content": (
                    "[{'type': 'text', 'text': '{\"error\": "
                    "\"MultipleDefinitionError(name=\\'sp\\', cells=(\\'MJUe\\', \\'vblA\\'))\"}'}]"
                ),
            }
        ]
    )

    assert sanitized == [
        {
            "idx": 88,
            "type": "tool_result",
            "safeText": "Notebook error: MultipleDefinitionError for sp",
            "signals": ["notebook_error"],
        }
    ]
    assert build_status_hints({"recentEvents": sanitized}) == ["Fixing duplicate sp definitions..."]


def test_slack_progress_run_cells_uses_recent_objects_for_status_hints() -> None:
    sanitized = sanitize_trace_events(
        [
            {
                "idx": 176,
                "type": "tool_use",
                "tool_name": "mcp__signalpilot-notebook__run_cells",
                "tool_input": {"session_id": "session-slack-1", "timeout": 120},
            }
        ]
    )

    assert build_status_hints(
        {
            "recentEvents": sanitized,
            "observedObjects": ["private-equity-db", "portfolio.customer_metrics"],
        }
    ) == [
        "Running portfolio.customer_metrics query...",
        "Running private-equity-db notebook cells...",
    ]


def test_slack_progress_status_hints_prefer_current_event_objects() -> None:
    assert build_status_hints(
        {
            "recentEvents": [
                {
                    "idx": 155,
                    "type": "tool_use",
                    "signals": ["contains_db_query"],
                    "objects": ["portfolio.customer_metrics", "portfolio.operating_initiatives"],
                }
            ],
            "observedObjects": ["portfolio.monthly_financials"],
        }
    ) == ["Querying portfolio.operating_initiatives..."]


@pytest.mark.asyncio
async def test_slack_progress_summarizer_uses_ai_for_concrete_status() -> None:
    seen_payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        seen_payloads.append(json.loads(body["messages"][0]["content"]))
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": '{"statusText":"Querying staging.fct_revenue...","shouldUpdate":true}',
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        summary = await SlackProgressSummarizer(
            model="claude-haiku-4-5-20251001",
            api_key="sk-ant-test",
            http_client=client,
        ).summarize(
            {
                "previousStatus": INITIAL_PROGRESS_TEXT,
                "observedSignals": ["contains_db_query"],
                "recentEvents": [
                    {
                        "idx": 1,
                        "type": "tool_use",
                        "toolName": "mcp__signalpilot-notebook__edit_notebook",
                        "signals": ["contains_db_query"],
                        "objects": ["private-equity-db", "staging.fct_revenue"],
                    }
                ],
            }
        )
    finally:
        await client.aclose()

    assert summary.status_text == "Querying staging.fct_revenue..."
    assert summary.should_update is True
    assert seen_payloads[0]["recentEvents"][0]["objects"] == ["private-equity-db", "staging.fct_revenue"]


@pytest.mark.asyncio
async def test_slack_progress_summarizer_accepts_fenced_json() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "```json\n"
                            '{"statusText":"Fixing MultipleDefinitionError in notebook structure...",'
                            '"shouldUpdate":true}'
                            "\n```"
                        ),
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        summary = await SlackProgressSummarizer(
            model="claude-haiku-4-5-20251001",
            api_key="sk-ant-test",
            http_client=client,
        ).summarize(
            {
                "previousStatus": INITIAL_PROGRESS_TEXT,
                "recentEvents": [
                    {
                        "idx": 88,
                        "type": "tool_result",
                        "safeText": "Notebook error: MultipleDefinitionError for sp",
                        "signals": ["notebook_error"],
                    }
                ],
            }
        )
    finally:
        await client.aclose()

    assert summary.status_text == "Fixing MultipleDefinitionError in notebook structure..."
    assert summary.should_update is True


@pytest.mark.asyncio
async def test_slack_progress_summarizer_retries_generic_ai_status() -> None:
    calls: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        payload = json.loads(body["messages"][0]["content"])
        calls.append(payload)
        text = (
            '{"statusText":"Building charts...","shouldUpdate":true}'
            if len(calls) == 1
            else '{"statusText":"Building EBITDA chart...","shouldUpdate":true}'
        )
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        summary = await SlackProgressSummarizer(
            model="claude-haiku-4-5-20251001",
            api_key="sk-ant-test",
            http_client=client,
        ).summarize(
            {
                "previousStatus": INITIAL_PROGRESS_TEXT,
                "observedSignals": ["builds_charts"],
                "observedObjects": ["portfolio.monthly_financials", "EBITDA chart"],
                "statusHints": ["Building EBITDA chart..."],
                "recentEvents": [
                    {
                        "idx": 164,
                        "type": "tool_use",
                        "toolName": "mcp__signalpilot-notebook__edit_notebook",
                        "signals": ["builds_charts"],
                        "objects": ["EBITDA chart"],
                    }
                ],
            }
        )
    finally:
        await client.aclose()

    assert summary.status_text == "Building EBITDA chart..."
    assert len(calls) == 2
    assert calls[1]["rejectedStatusText"] == "Building charts..."


@pytest.mark.asyncio
async def test_slack_progress_summarizer_skips_update_when_ai_stays_generic() -> None:
    calls: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append(json.loads(body["messages"][0]["content"]))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": '{"statusText":"Running notebook cells...","shouldUpdate":true}'}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        summary = await SlackProgressSummarizer(
            model="claude-haiku-4-5-20251001",
            api_key="sk-ant-test",
            http_client=client,
        ).summarize(
            {
                "previousStatus": INITIAL_PROGRESS_TEXT,
                "statusHints": ["Running portfolio.customer_metrics query..."],
                "recentEvents": [
                    {
                        "idx": 176,
                        "type": "tool_use",
                        "toolName": "mcp__signalpilot-notebook__run_cells",
                        "signals": ["runs_notebook_cells"],
                    }
                ],
            }
        )
    finally:
        await client.aclose()

    assert summary.status_text == INITIAL_PROGRESS_TEXT
    assert summary.should_update is False
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_slack_progress_summarizer_skips_update_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    summarizer = SlackProgressSummarizer(model="claude-small-test")

    summary = await summarizer.summarize(
        {
            "previousStatus": INITIAL_PROGRESS_TEXT,
            "observedSignals": ["contains_db_query"],
            "recentEvents": [],
        }
    )

    assert summary.status_text == INITIAL_PROGRESS_TEXT
    assert summary.should_update is False


@pytest.mark.asyncio
async def test_slack_progress_summarizer_skips_update_on_invalid_json_and_timeout() -> None:
    async def invalid_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": [{"type": "text", "text": "not json"}]})

    invalid_client = httpx.AsyncClient(transport=httpx.MockTransport(invalid_json_handler))
    try:
        invalid_summary = await SlackProgressSummarizer(
            model="claude-small-test",
            api_key="sk-ant-test",
            http_client=invalid_client,
        ).summarize(
            {
                "previousStatus": INITIAL_PROGRESS_TEXT,
                "observedSignals": ["notebook_edited"],
                "recentEvents": [],
            }
        )
    finally:
        await invalid_client.aclose()

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    timeout_client = httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler))
    try:
        timeout_summary = await SlackProgressSummarizer(
            model="claude-small-test",
            api_key="sk-ant-test",
            http_client=timeout_client,
        ).summarize(
            {
                "previousStatus": INITIAL_PROGRESS_TEXT,
                "observedSignals": ["runs_notebook_cells"],
                "recentEvents": [],
            }
        )
    finally:
        await timeout_client.aclose()

    assert invalid_summary.status_text == INITIAL_PROGRESS_TEXT
    assert invalid_summary.should_update is False
    assert timeout_summary.status_text == INITIAL_PROGRESS_TEXT
    assert timeout_summary.should_update is False


@pytest.mark.asyncio
async def test_slack_progress_reporter_ignores_slack_update_failure() -> None:
    slack = AsyncMock()
    slack.update_message.side_effect = RuntimeError("slack update failed")
    reporter = SlackProgressReporter(
        slack=slack,
        session_factory=AsyncMock(),
        org_id="org-a",
        user_id="user-a",
        thread_id="session-slack-1",
        source_prompt="Use my fin db and dbt project",
        channel_id="C1",
        message_ts="2.0",
        interval_seconds=0.1,
        summarizer=AsyncMock(
            summarize=AsyncMock(return_value=ProgressSummary("Querying portfolio.customer_metrics...", True))
        ),
    )

    async def fetch_events():
        return [
            {
                "idx": 1,
                "type": "tool_use",
                "tool_name": "mcp__signalpilot-notebook__run_cells",
                "tool_input": {},
                "created_at": 100.0,
            }
        ]

    reporter._fetch_events = fetch_events

    await reporter._tick()

    slack.update_message.assert_awaited_once()
    assert reporter.previous_status == INITIAL_PROGRESS_TEXT
