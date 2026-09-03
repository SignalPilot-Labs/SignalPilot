from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from gateway.dashboard import store as dashboard_store
from gateway.dashboard import top_level_authoring
from gateway.dashboard.domain import ChartDefinition
from gateway.dashboard.progressive_authoring import validate_dashboard_plan
from gateway.db.models import GatewayBase
from gateway.models.dashboards import DashboardChartIntent, DashboardPlan, DashboardSemanticContext


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
                            "semantic_source": "dbt_project",
                            "aggregation_inferred": True,
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
        layout={"x": index * 12, "y": 0, "w": 12, "h": 6},
        visualization="kpi",
        shared_filter_ids=[],
    )


def _plan(count: int = 2) -> DashboardPlan:
    return DashboardPlan(name="Revenue", timezone="UTC", intents=[_intent(index) for index in range(count)])


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
            "visualization": {"type": "big_number", "config": {"field": "orders.revenue"}},
            "signalPilot": {"crossFilter": False, "provenanceRef": f"plan:{chart_id}"},
        }
    )


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def _begin(db: AsyncSession):
    return await dashboard_store.create_top_level_authoring_session(
        db,
        org_id="org-a",
        user_id="user-a",
        dashboard_id=None,
        base_version_id=None,
        context=_context(),
        prompt="Create a revenue dashboard",
        timezone="UTC",
        conversation_id="conversation-a",
        run_id="run-a",
    )


@pytest.mark.asyncio
async def test_top_level_tools_accept_out_of_order_charts_and_finalize_deterministically(
    db_session: AsyncSession,
) -> None:
    created = await _begin(db_session)
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    planned = await top_level_authoring.accept_plan(
        db_session,
        session=row,
        context=_context(),
        plan=_plan(),
        expected_plan_revision=0,
        tool_call_id="tool-plan",
    )
    assert (planned.plan_revision, planned.expected_count) == (1, 2)

    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    second = await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-1",
        chart=_chart("chart-1"),
        tool_call_id="tool-chart-1",
    )
    assert (second.status, second.ready_count) == ("ready", 1)

    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    first = await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-0",
        chart=_chart("chart-0"),
        tool_call_id="tool-chart-0",
    )
    assert (first.status, first.ready_count) == ("ready", 2)

    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    finalized = await top_level_authoring.finalize_preview(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        expected_draft_revision=first.draft_revision,
        tool_call_id="tool-finalize",
    )
    assert finalized.status == "preview_ready"
    assert [chart.id for chart in finalized.session.definition.charts] == ["chart-0", "chart-1"]
    assert finalized.session.status == "preview"

    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    event_count = len(row.events_json)
    retried = await top_level_authoring.finalize_preview(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        expected_draft_revision=first.draft_revision,
        tool_call_id="tool-finalize-retry",
    )
    assert retried.draft_revision == finalized.draft_revision
    assert len(row.events_json) == event_count


@pytest.mark.asyncio
async def test_rejected_chart_preserves_ready_work_and_allows_one_repair(
    db_session: AsyncSession,
) -> None:
    created = await _begin(db_session)
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    await top_level_authoring.accept_plan(
        db_session,
        session=row,
        context=_context(),
        plan=_plan(),
        expected_plan_revision=0,
        tool_call_id="tool-plan",
    )
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    ready = await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-0",
        chart=_chart("chart-0"),
        tool_call_id="tool-ready",
    )
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    rejected = await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-1",
        chart=_chart("wrong-chart"),
        tool_call_id="tool-rejected",
    )
    assert (rejected.status, rejected.ready_count, rejected.failed_count) == ("rejected", 1, 1)
    assert rejected.validation_issues[0].code == "dashboard_payload_invalid"

    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    repaired = await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-1",
        chart=_chart("chart-1"),
        tool_call_id="tool-repair",
    )
    assert (repaired.status, repaired.ready_count, repaired.failed_count) == ("ready", 2, 0)
    assert ready.draft_revision < repaired.draft_revision


@pytest.mark.asyncio
async def test_identical_plan_and_chart_retries_are_idempotent(
    db_session: AsyncSession,
) -> None:
    created = await _begin(db_session)
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    planned = await top_level_authoring.accept_plan(
        db_session,
        session=row,
        context=_context(),
        plan=_plan(1),
        expected_plan_revision=0,
        tool_call_id="tool-plan",
    )
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    event_count = len(row.events_json)
    retried_plan = await top_level_authoring.accept_plan(
        db_session,
        session=row,
        context=_context(),
        plan=_plan(1),
        expected_plan_revision=0,
        tool_call_id="tool-plan-retry",
    )
    assert retried_plan.draft_revision == planned.draft_revision
    assert len(row.events_json) == event_count

    accepted = await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-0",
        chart=_chart("chart-0"),
        tool_call_id="tool-chart",
    )
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    event_count = len(row.events_json)
    retried_chart = await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-0",
        chart=_chart("chart-0"),
        tool_call_id="tool-chart-retry",
    )
    assert retried_chart.draft_revision == accepted.draft_revision
    assert len(row.events_json) == event_count

    operations = [{"operation": "rename_dashboard", "name": "Executive revenue"}]
    updated = await top_level_authoring.apply_operations(
        db_session,
        session=row,
        context=_context(),
        expected_draft_revision=accepted.draft_revision,
        operations=operations,
        tool_call_id="tool-operations",
    )
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    event_count = len(row.events_json)
    retried_operations = await top_level_authoring.apply_operations(
        db_session,
        session=row,
        context=_context(),
        expected_draft_revision=accepted.draft_revision,
        operations=operations,
        tool_call_id="tool-operations-retry",
    )
    assert retried_operations.draft_revision == updated.draft_revision
    assert len(row.events_json) == event_count


@pytest.mark.asyncio
async def test_required_chart_failure_blocks_finalize_and_allows_only_one_repair(
    db_session: AsyncSession,
) -> None:
    created = await _begin(db_session)
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    await top_level_authoring.accept_plan(
        db_session,
        session=row,
        context=_context(),
        plan=_plan(),
        expected_plan_revision=0,
        tool_call_id="tool-plan",
    )
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    first_failure = await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-0",
        chart=_chart("wrong-chart"),
        tool_call_id="tool-failed-1",
    )
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    with pytest.raises(
        top_level_authoring.AuthoringContractError,
        match="Every required dashboard chart",
    ):
        await top_level_authoring.finalize_preview(
            db_session,
            session=row,
            context=_context(),
            plan_revision=1,
            expected_draft_revision=first_failure.draft_revision,
            tool_call_id="tool-finalize",
        )
    await top_level_authoring.accept_chart(
        db_session,
        session=row,
        context=_context(),
        plan_revision=1,
        chart_id="chart-0",
        chart=_chart("wrong-chart-2"),
        tool_call_id="tool-failed-2",
    )
    row = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="user-a", session_id=created.id
    )
    assert row is not None
    with pytest.raises(
        top_level_authoring.AuthoringContractError,
        match="repair limit",
    ):
        await top_level_authoring.accept_chart(
            db_session,
            session=row,
            context=_context(),
            plan_revision=1,
            chart_id="chart-0",
            chart=_chart("chart-0"),
            tool_call_id="tool-failed-3",
        )


def test_plan_validation_rejects_invented_semantic_fields() -> None:
    payload = _plan(1).model_dump(mode="json")
    payload["intents"][0]["metrics"] = ["orders.invented"]
    with pytest.raises(ValueError, match="Unknown metric"):
        validate_dashboard_plan(DashboardPlan.model_validate(payload), _context())


def test_gateway_runtime_has_no_nested_dashboard_model(tmp_path: Path = Path(".")) -> None:
    root = Path(__file__).parents[1] / "gateway" / "dashboard"
    source = "\n".join(path.read_text() for path in root.glob("*.py"))
    assert "class DashboardAuthoringAgent" not in source
    assert "class ProgressiveDashboardAuthoringAgent" not in source
