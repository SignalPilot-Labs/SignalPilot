from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.analysis_delivery.model_client import (
    AnthropicMessagesError,
    ClaudeAgentSDKResult,
    ClaudeAgentSDKStructuredClient,
)
from gateway.api import dashboards as dashboard_api
from gateway.dashboard import store as dashboard_store
from gateway.dashboard.authoring import DashboardAuthoringAgent
from gateway.dashboard.domain import ChartDefinition
from gateway.dashboard.progressive_authoring import (
    ProgressiveDashboardAuthoringAgent,
    ProviderCallGate,
    assemble_dashboard_definition,
    validate_dashboard_plan,
)
from gateway.dashboard.semantic_resolver import _scan_materialized_project
from gateway.db.models import GatewayBase
from gateway.models.dashboards import (
    DashboardAuthoringRequest,
    DashboardChartIntent,
    DashboardPlan,
    DashboardSemanticContext,
)


def _context() -> DashboardSemanticContext:
    return DashboardSemanticContext.model_validate(
        {
            "project_id": "project-a",
            "commit_sha": "a" * 40,
            "connection_name": "warehouse",
            "connection_type": "mssql",
            "physical_schema_fingerprint": "physical",
            "semantic_fingerprint": "semantic",
            "explores": [
                {
                    "name": "orders",
                    "label": "Orders",
                    "relation": "dbo.orders",
                    "dimensions": [
                        {
                            "field_id": "orders.region",
                            "column": "region",
                            "logical_type": "string",
                        }
                    ],
                    "metrics": [
                        {
                            "field_id": "orders.revenue",
                            "column": "revenue",
                            "logical_type": "number",
                            "label": "Revenue",
                            "aggregation": "sum",
                            "approval_source": "test",
                            "human_verified": True,
                        }
                    ],
                }
            ],
        }
    )


def _intent(index: int) -> DashboardChartIntent:
    return DashboardChartIntent(
        chart_id=f"chart-{index}",
        tile_id=f"tile-{index}",
        label=f"Revenue {index}",
        question=f"What is revenue {index}?",
        description="Approved revenue KPI.",
        required_concepts=["revenue"],
        explore_name="orders",
        dimensions=[],
        metrics=["orders.revenue"],
        section="Overview",
        order=index,
        layout={"x": (index % 3) * 12, "y": (index // 3) * 6, "w": 12, "h": 6},
        visualization="kpi",
        shared_filter_ids=[],
    )


def _plan(count: int) -> DashboardPlan:
    return DashboardPlan(name="Revenue", intents=[_intent(index) for index in range(count)])


def _chart(chart_id: str) -> ChartDefinition:
    return ChartDefinition.model_validate(
        {
            "id": chart_id,
            "title": chart_id,
            "question": "What is approved revenue?",
            "description": "Approved revenue KPI.",
            "query": {
                "kind": "semantic",
                "exploreName": "orders",
                "dimensions": [],
                "metrics": ["orders.revenue"],
                "filters": {},
                "sorts": [],
                "limit": 1,
                "projectId": "project-a",
                "commitSha": "a" * 40,
            },
            "visualization": {
                "type": "big_number",
                "config": {"field": "orders.revenue"},
            },
            "signalPilot": {"crossFilter": False, "provenanceRef": f"plan:{chart_id}"},
        }
    )


def _stable_id_validator(expected: str):
    def validate(chart: ChartDefinition) -> None:
        if chart.id != expected:
            raise ValueError("wrong stable ID")

    return validate


class _ConcurrentChartClient:
    def __init__(self, *, invalid_once: str | None = None) -> None:
        self.active = 0
        self.max_active = 0
        self.calls: dict[str, int] = {}
        self.invalid_once = invalid_once

    async def create_message(self, request_body: dict) -> dict:
        payload = json.loads(request_body["messages"][0]["content"])
        chart_id = payload["intent"]["chart_id"]
        self.calls[chart_id] = self.calls.get(chart_id, 0) + 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.02)
        self.active -= 1
        chart = _chart(chart_id).model_dump(mode="json", by_alias=True)
        if self.invalid_once == chart_id and self.calls[chart_id] == 1:
            chart["id"] = "wrong-chart"
        return {
            "content": [
                {
                    "type": "tool_use",
                    "name": "submit_chart_definition",
                    "input": chart,
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


class _ProgressiveApiClient:
    def __init__(self) -> None:
        self.fail_second_chart = True
        self.invalid_merge = False
        self.calls: dict[str, int] = {}
        self.chart_calls: dict[str, int] = {}

    async def create_message(self, request_body: dict) -> dict:
        tool = request_body["tool_choice"]["name"]
        self.calls[tool] = self.calls.get(tool, 0) + 1
        if tool == "submit_dashboard_plan":
            value = _plan(2).model_dump(mode="json", by_alias=True)
        elif tool == "submit_chart_definition":
            payload = json.loads(request_body["messages"][0]["content"])
            chart_id = payload["intent"]["chart_id"]
            self.chart_calls[chart_id] = self.chart_calls.get(chart_id, 0) + 1
            value = _chart(chart_id).model_dump(mode="json", by_alias=True)
            if chart_id == "chart-1" and self.fail_second_chart:
                value["id"] = "wrong-chart"
        elif tool == "submit_dashboard_merge":
            value = {
                "name": "Merged revenue",
                "description": "Validated revenue dashboard.",
                "tiles": [
                    {
                        "chart_id": "chart-0",
                        "title": "Revenue now",
                        "section": "Overview",
                        "order": 0,
                        "layout": {"x": 0, "y": 0, "w": 18, "h": 6},
                    },
                    {
                        "chart_id": "chart-1",
                        "title": "Revenue comparison",
                        "section": "Overview",
                        "order": 1,
                        "layout": {"x": 18, "y": 0, "w": 18, "h": 6},
                    },
                ],
            }
            if self.invalid_merge:
                value["tiles"] = value["tiles"][:1]
        else:
            raise AssertionError(f"Unexpected tool: {tool}")
        return {
            "content": [{"type": "tool_use", "name": tool, "input": value}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }


class _RateLimitedChartClient:
    def __init__(self) -> None:
        self.calls = 0

    async def create_message(self, request_body: dict) -> dict:
        self.calls += 1
        if self.calls == 1:
            raise AnthropicMessagesError(
                status_code=429,
                error_type="rate_limit_error",
                provider_message="raw provider detail must stay private",
                request_id="request-private",
                request_body_chars=100,
                retry_after="0.02",
            )
        payload = json.loads(request_body["messages"][0]["content"])
        chart = _chart(payload["intent"]["chart_id"])
        return {
            "content": [
                {
                    "type": "tool_use",
                    "name": "submit_chart_definition",
                    "input": chart.model_dump(mode="json", by_alias=True),
                }
            ]
        }


class _HangingChartClient:
    def __init__(self) -> None:
        self.started = 0
        self.cancelled = 0
        self.all_started = asyncio.Event()

    async def create_message(self, request_body: dict) -> dict:
        self.started += 1
        if self.started == 5:
            self.all_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_nested_dbt_project_scans_the_manifest_resolved_directory(tmp_path: Path) -> None:
    dbt_dir = tmp_path / "dumpsters_dbt"
    models = dbt_dir / "models"
    models.mkdir(parents=True)
    (dbt_dir / "dbt_project.yml").write_text(
        "name: dumpsters\nversion: '1.0'\nprofile: dumpsters\nmodel-paths: ['models']\n",
        encoding="utf-8",
    )
    for index in range(247):
        (models / f"model_{index}.sql").write_text("select 1 as id\n", encoding="utf-8")
    source_tables = "\n".join(f"      - name: source_{index}" for index in range(11))
    (models / "sources.yml").write_text(
        f"version: 2\nsources:\n  - name: raw\n    tables:\n{source_tables}\n",
        encoding="utf-8",
    )

    project = _scan_materialized_project(tmp_path, {"dbt_project_dir": "dumpsters_dbt"})

    assert len(project.models) == 247
    assert project.sources["raw"].tables == [f"source_{index}" for index in range(11)]


@pytest.mark.asyncio
async def test_zero_explores_never_invokes_an_authoring_model(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_context = _context().model_copy(update={"explores": []})

    async def resolve_context(*_args, **_kwargs):
        return empty_context

    async def no_chat_run(*_args, **_kwargs):
        return None

    async def reject_model(*_args, **_kwargs):
        raise AssertionError("model must not be resolved for zero explores")

    monkeypatch.setattr(dashboard_api.resolver, "resolve", resolve_context)
    monkeypatch.setattr(dashboard_api, "_request_chat_run", no_chat_run)
    monkeypatch.setattr(dashboard_api, "_dashboard_authoring_agent", reject_model)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )

    with pytest.raises(HTTPException, match="no governed explores") as exc_info:
        await dashboard_api.create_dashboard_authoring_session(
            DashboardAuthoringRequest(
                prompt="Create a dashboard",
                project_id="project-a",
                commit_sha="a" * 40,
            ),
            store,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_zero_approved_metrics_never_invokes_an_authoring_model(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context()
    empty_metric_context = context.model_copy(
        update={"explores": [explore.model_copy(update={"metrics": []}) for explore in context.explores]}
    )

    async def resolve_context(*_args, **_kwargs):
        return empty_metric_context

    async def no_chat_run(*_args, **_kwargs):
        return None

    async def reject_model(*_args, **_kwargs):
        raise AssertionError("model must not be resolved without approved metrics")

    monkeypatch.setattr(dashboard_api.resolver, "resolve", resolve_context)
    monkeypatch.setattr(dashboard_api, "_request_chat_run", no_chat_run)
    monkeypatch.setattr(dashboard_api, "_dashboard_authoring_agent", reject_model)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )

    with pytest.raises(HTTPException, match="no approved dashboard metrics") as exc_info:
        await dashboard_api.create_dashboard_authoring_session(
            DashboardAuthoringRequest(
                prompt="Create a dashboard",
                project_id="project-a",
                commit_sha="a" * 40,
            ),
            store,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_progress_events_are_metadata_only(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    emitted: list[dict] = []

    async def append_event(_db, **kwargs):
        emitted.append(kwargs["payload"])

    monkeypatch.setattr(dashboard_api.chat_store, "append_event", append_event)
    store = SimpleNamespace(session=db_session)

    await dashboard_api._emit_progressive_dashboard_event(
        store,
        run_id="run-a",
        phase="chart_failed",
        label="Revenue chart could not be completed",
        session_id="session-a",
        chart_id="chart-a",
        ready_count=2,
        failed_count=1,
        expected_count=3,
        status="failed",
        attempt=2,
        draft_revision=8,
    )

    assert set(emitted[0]) == {
        "scope",
        "phase",
        "label",
        "authoring_session_id",
        "chart_id",
        "ready_count",
        "failed_count",
        "expected_count",
        "status",
        "attempt",
        "draft_revision",
    }
    serialized = json.dumps(emitted[0]).lower()
    assert all(token not in serialized for token in ("select ", "rows", "credential", "prompt", "traceback"))


@pytest.mark.asyncio
async def test_partial_failure_is_visible_and_retry_only_regenerates_the_failed_chart(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _ProgressiveApiClient()
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)

    async def resolve_context(*_args, **_kwargs):
        return _context()

    async def authoring_agent(*_args, **_kwargs):
        return agent, False

    async def no_chat_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dashboard_api.resolver, "resolve", resolve_context)
    monkeypatch.setattr(dashboard_api, "_dashboard_authoring_agent", authoring_agent)
    monkeypatch.setattr(dashboard_api, "_request_chat_run", no_chat_run)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )

    partial = await dashboard_api.create_dashboard_authoring_session(
        DashboardAuthoringRequest(
            prompt="Create a revenue dashboard",
            project_id="project-a",
            commit_sha="a" * 40,
        ),
        store,
    )

    assert partial.status == "partial_failed"
    assert partial.definition is not None
    assert [chart.id for chart in partial.definition.charts] == ["chart-0"]
    first = next(draft for draft in partial.chart_drafts if draft.chart_id == "chart-0")
    assert first.attempt_count == 1
    failed = next(draft for draft in partial.chart_drafts if draft.chart_id == "chart-1")
    assert failed.status == "failed"
    assert failed.attempt_count == 2
    assert failed.safe_error == "This chart could not be validated against the governed semantic model."

    client.fail_second_chart = False
    ready = await dashboard_api.retry_failed_dashboard_charts(partial.id, store)

    assert ready.status == "preview"
    assert ready.definition is not None
    assert ready.definition.name == "Merged revenue"
    assert [chart.id for chart in ready.definition.charts] == ["chart-0", "chart-1"]
    assert client.chart_calls == {"chart-0": 1, "chart-1": 3}
    first = next(draft for draft in ready.chart_drafts if draft.chart_id == "chart-0")
    assert first.attempt_count == 1
    assert first.definition == _chart("chart-0")


@pytest.mark.asyncio
async def test_invalid_merge_repairs_once_then_uses_query_preserving_fallback(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _ProgressiveApiClient()
    client.fail_second_chart = False
    client.invalid_merge = True
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)

    async def resolve_context(*_args, **_kwargs):
        return _context()

    async def authoring_agent(*_args, **_kwargs):
        return agent, False

    async def no_chat_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr(dashboard_api.resolver, "resolve", resolve_context)
    monkeypatch.setattr(dashboard_api, "_dashboard_authoring_agent", authoring_agent)
    monkeypatch.setattr(dashboard_api, "_request_chat_run", no_chat_run)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )

    ready = await dashboard_api.create_dashboard_authoring_session(
        DashboardAuthoringRequest(
            prompt="Create a revenue dashboard",
            project_id="project-a",
            commit_sha="a" * 40,
        ),
        store,
    )

    assert ready.status == "preview"
    assert ready.definition is not None
    assert ready.definition.name == "Revenue"
    assert client.calls["submit_dashboard_merge"] == 2
    assert {chart.id: chart.query for chart in ready.definition.charts} == {
        "chart-0": _chart("chart-0").query,
        "chart-1": _chart("chart-1").query,
    }
    assert [(tile.x, tile.y, tile.w) for tile in ready.definition.tiles] == [
        (0, 0, 12),
        (12, 0, 12),
    ]


@pytest.mark.asyncio
async def test_nine_chart_agents_never_exceed_five_concurrent_calls() -> None:
    client = _ConcurrentChartClient()
    agent = ProgressiveDashboardAuthoringAgent(
        model="test-model",
        model_client=client,
        gate=ProviderCallGate(concurrency=5),
    )
    plan = _plan(9)

    await asyncio.gather(
        *[
            agent.create_chart(
                intent=intent,
                context=_context(),
                filters=[],
                validator=lambda _chart: None,
            )
            for intent in plan.intents
        ]
    )

    assert client.max_active == 5
    assert sum(client.calls.values()) == 9


@pytest.mark.asyncio
async def test_oauth_uses_native_structured_output_only_for_chart_agents() -> None:
    native_calls: list[bool] = []

    async def query_runner(_prompt: str, options: dict) -> ClaudeAgentSDKResult:
        native = "output_format" in options
        native_calls.append(native)
        value = (
            _chart("chart-0").model_dump(mode="json", by_alias=True)
            if native
            else _plan(1).model_dump(mode="json", by_alias=True)
        )
        return ClaudeAgentSDKResult(
            structured_output=value if native else None,
            result_text=None if native else json.dumps(value),
            is_error=False,
        )

    oauth_client = ClaudeAgentSDKStructuredClient(
        oauth_token="oauth-test",
        timeout_seconds=1,
        use_native_structured_output=False,
        query_runner=query_runner,
    )
    agent = ProgressiveDashboardAuthoringAgent(
        model="test-model",
        model_client=oauth_client,
    )

    await agent.create_plan(
        prompt="Build revenue",
        semantic_projection={"explores": []},
        validator=lambda _plan: None,
    )
    await agent.create_chart(
        intent=_intent(0),
        context=_context(),
        filters=[],
        validator=lambda _chart: None,
    )

    assert native_calls == [False, True]


@pytest.mark.asyncio
async def test_oauth_chart_transport_repairs_once_with_json_contract() -> None:
    native_calls: list[bool] = []

    async def query_runner(prompt: str, options: dict) -> ClaudeAgentSDKResult:
        native = "output_format" in options
        native_calls.append(native)
        if native:
            raise RuntimeError("native decoder unavailable")
        value = _chart("chart-0").model_dump(mode="json", by_alias=True)
        return ClaudeAgentSDKResult(
            structured_output=None,
            result_text=json.dumps(value),
            is_error=False,
        )

    oauth_client = ClaudeAgentSDKStructuredClient(
        oauth_token="oauth-test",
        timeout_seconds=1,
        use_native_structured_output=False,
        query_runner=query_runner,
    )
    agent = ProgressiveDashboardAuthoringAgent(
        model="test-model",
        model_client=oauth_client,
    )

    result = await agent.create_chart(
        intent=_intent(0),
        context=_context(),
        filters=[],
        validator=lambda _chart: None,
    )

    assert result.attempt_count == 2
    assert native_calls == [True, False]


@pytest.mark.asyncio
async def test_cancellation_stops_active_and_pending_chart_calls() -> None:
    client = _HangingChartClient()
    agent = ProgressiveDashboardAuthoringAgent(
        model="test-model",
        model_client=client,
        gate=ProviderCallGate(concurrency=5),
    )
    tasks = [
        asyncio.create_task(
            agent.create_chart(
                intent=intent,
                context=_context(),
                filters=[],
                validator=lambda _chart: None,
            )
        )
        for intent in _plan(9).intents
    ]

    await asyncio.wait_for(client.all_started.wait(), timeout=1)
    for task in tasks:
        task.cancel()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert client.started == 5
    assert client.cancelled == 5
    assert all(isinstance(result, asyncio.CancelledError) for result in results)


@pytest.mark.asyncio
async def test_only_the_invalid_chart_uses_its_repair_attempt() -> None:
    client = _ConcurrentChartClient(invalid_once="chart-1")
    agent = ProgressiveDashboardAuthoringAgent(
        model="test-model",
        model_client=client,
    )
    plan = _plan(2)

    results = await asyncio.gather(
        *[
            agent.create_chart(
                intent=intent,
                context=_context(),
                filters=[],
                validator=_stable_id_validator(intent.chart_id),
            )
            for intent in plan.intents
        ]
    )

    assert client.calls == {"chart-0": 1, "chart-1": 2}
    assert [result.attempt_count for result in results] == [1, 2]


@pytest.mark.asyncio
async def test_retry_after_delays_the_single_allowed_repair_call() -> None:
    client = _RateLimitedChartClient()
    agent = ProgressiveDashboardAuthoringAgent(model="test-model", model_client=client)
    started = time.monotonic()

    result = await agent.create_chart(
        intent=_intent(0),
        context=_context(),
        filters=[],
        validator=lambda _chart: None,
    )

    assert result.attempt_count == 2
    assert client.calls == 2
    assert time.monotonic() - started >= 0.018


@pytest.mark.asyncio
async def test_retry_reset_keeps_validated_chart_unchanged(db_session: AsyncSession) -> None:
    plan = _plan(2)
    created = await dashboard_store.create_progressive_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=None,
        base_version_id=None,
        context=_context(),
        plan=plan,
        prompt="Create revenue dashboard",
        model="test-model",
        conversation_id="conversation-a",
    )
    chart = _chart("chart-0")
    partial = assemble_dashboard_definition(
        plan=plan,
        charts=[chart],
        context=_context(),
        timezone="UTC",
    )
    await dashboard_store.update_progressive_chart(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=created.id,
        chart_id="chart-0",
        status="ready",
        attempt_count=1,
        definition=chart,
        partial_definition=partial,
        phase="chart_ready",
        safe_label="Revenue 0 is ready",
    )
    await dashboard_store.update_progressive_chart(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=created.id,
        chart_id="chart-1",
        status="failed",
        attempt_count=2,
        safe_error="Safe chart failure",
        phase="chart_failed",
        safe_label="Revenue 1 failed",
    )
    await dashboard_store.finalize_progressive_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=created.id,
        definition=partial,
        status="partial_failed",
        summary="One chart failed.",
        phase="chart_failed",
    )

    reset = await dashboard_store.reset_failed_progressive_charts(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=created.id,
    )

    ready = next(draft for draft in reset.chart_drafts if draft.chart_id == "chart-0")
    failed = next(draft for draft in reset.chart_drafts if draft.chart_id == "chart-1")
    assert ready.status == "ready"
    assert ready.definition == chart
    assert failed.status == "pending"
    assert failed.definition is None
    assert reset.definition is not None
    assert [item.id for item in reset.definition.charts] == ["chart-0"]


def test_completion_order_cannot_change_stable_chart_order() -> None:
    plan = _plan(3)
    completed = [_chart("chart-2"), _chart("chart-0"), _chart("chart-1")]
    definition = assemble_dashboard_definition(
        plan=plan,
        charts=completed,
        context=_context(),
        timezone="UTC",
        deterministic_fallback=True,
    )

    validate_dashboard_plan(plan, _context())
    assert [chart.id for chart in definition.charts] == ["chart-0", "chart-1", "chart-2"]
    source_queries = {chart.id: chart.query for chart in completed}
    assert {chart.id: chart.query for chart in definition.charts} == source_queries
