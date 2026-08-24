"""Phase 3 typed authoring and explicit-apply contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.dashboard import store as dashboard_store
from gateway.dashboard.authoring import DashboardAuthoringAgent, materialize_agent_draft
from gateway.dashboard.domain import DashboardDefinition
from gateway.dashboard.operations import apply_dashboard_operations
from gateway.db.models import GatewayBase, GatewayDashboardResult
from gateway.models.dashboards import DashboardSemanticContext

FIXTURE = Path(__file__).parents[2] / "web/dashboard/lightdash-contract/fixtures/five-components.json"


def _context() -> DashboardSemanticContext:
    definition = _definition()
    return DashboardSemanticContext(
        project_id=definition.signalPilot.projectId,
        commit_sha=definition.signalPilot.commitSha,
        connection_name=definition.signalPilot.connectionName,
        connection_type="mssql",
        physical_schema_fingerprint="physical",
        semantic_fingerprint=definition.signalPilot.semanticFingerprint,
        explores=[],
    )


def _definition() -> DashboardDefinition:
    fixture = json.loads(FIXTURE.read_text())
    return DashboardDefinition.model_validate(
        {
            "schemaVersion": 1,
            "name": fixture["dashboard"]["name"],
            "description": fixture["dashboard"]["description"],
            "filters": fixture["dashboard"]["filters"],
            "tiles": fixture["dashboard"]["tiles"],
            "charts": fixture["charts"],
            "signalPilot": fixture["signalPilot"],
        }
    )


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_typed_update_changes_only_the_targeted_chart() -> None:
    source = _definition()
    updated = apply_dashboard_operations(
        source,
        [
            {
                "operation": "describe_chart",
                "chart_id": "chart-bar",
                "description": "Approved regional revenue only.",
            }
        ],
    )
    assert updated.charts[2].description == "Approved regional revenue only."
    assert updated.charts[:2] == source.charts[:2]
    assert updated.charts[3:] == source.charts[3:]
    assert updated.tiles == source.tiles


def test_replace_metric_updates_query_and_visual_encoding_together() -> None:
    updated = apply_dashboard_operations(
        _definition(),
        [
            {
                "operation": "replace_metric",
                "chart_id": "chart-bar",
                "old_metric": "orders.revenue",
                "new_metric": "orders.gross_margin",
            }
        ],
    )
    chart = next(chart for chart in updated.charts if chart.id == "chart-bar")
    assert chart.query.kind == "semantic"
    assert chart.query.metrics == ["orders.gross_margin"]
    assert chart.visualization.type == "cartesian"
    assert chart.visualization.config.layout.yField == ["orders.gross_margin"]


class _ModelClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.request: dict | None = None

    async def create_message(self, request_body: dict) -> dict:
        self.request = request_body
        return {
            "content": [
                {
                    "type": "tool_use",
                    "name": "submit_dashboard_draft",
                    "input": self.payload,
                }
            ]
        }


@pytest.mark.asyncio
async def test_agent_update_is_forced_through_typed_operations() -> None:
    client = _ModelClient(
        {
            "summary": "Renamed the dashboard.",
            "operations": [{"operation": "rename_dashboard", "name": "Executive revenue"}],
        }
    )
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)
    draft = await agent.draft(
        prompt="Rename this dashboard",
        context=_context(),
        base_definition=_definition(),
    )
    materialized = materialize_agent_draft(draft, base_definition=_definition())
    assert materialized.name == "Executive revenue"
    assert client.request is not None
    assert client.request["tool_choice"] == {"type": "tool", "name": "submit_dashboard_draft"}
    assert "question is a concise natural-language question" in client.request["system"]
    chart_schema = client.request["tools"][0]["input_schema"]["$defs"]["ChartDefinition"]
    assert "question" in chart_schema["properties"]


@pytest.mark.asyncio
async def test_apply_is_explicit_and_records_authoring_provenance(db_session: AsyncSession) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        definition=_definition(),
    )
    definition = created.version.definition.model_copy(update={"name": "Agent preview"})
    preview = await dashboard_store.create_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        base_version_id=created.version.id,
        definition=definition,
        operations=[{"operation": "rename_dashboard", "name": "Agent preview"}],
        prompt="Rename this dashboard",
        summary="Renamed the dashboard.",
        agent_run_id="agent-run-1",
        model="test-model",
        requires_custom_sql_confirmation=False,
        custom_sql_confirmed=False,
    )
    still_current = await dashboard_store.get_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
    )
    assert still_current is not None
    assert still_current.version.id == created.version.id

    applied = await dashboard_store.apply_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=preview.id,
        expected_current_version_id=created.version.id,
        visible_complete_result_ids=[],
    )
    assert applied.version.ordinal == 2
    assert applied.version.definition.name == "Agent preview"
    assert applied.version.authoring_provenance["authoring_session_id"] == preview.id
    assert applied.version.authoring_provenance["agent_run_id"] == "agent-run-1"


@pytest.mark.asyncio
async def test_new_dashboard_apply_promotes_only_the_exact_complete_preview_result(
    db_session: AsyncSession,
) -> None:
    preview = await dashboard_store.create_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=None,
        base_version_id=None,
        definition=_definition(),
        operations=[],
        prompt="Create a governed dashboard",
        summary="Created five governed charts.",
        agent_run_id="agent-run-new",
        model="test-model",
        requires_custom_sql_confirmation=False,
        custom_sql_confirmed=False,
    )
    result = GatewayDashboardResult(
        id="preview-result",
        dashboard_id=f"draft:{preview.id}",
        version_id=f"draft:{preview.id}",
        chart_id="chart-kpi",
        org_id="org-a",
        execution_id="execution-a",
        structured_result_id="structured-a",
        cache_key="c" * 64,
        sql_hash="s" * 64,
        parameter_hash="p" * 64,
        tables_json=["dbo.orders"],
        semantic_definition_json={"metric": "orders.revenue"},
        completeness="complete",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    db_session.add(result)
    await db_session.commit()

    applied = await dashboard_store.apply_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=preview.id,
        expected_current_version_id=None,
        visible_complete_result_ids=[result.id],
    )
    promoted = (
        await db_session.execute(select(GatewayDashboardResult).where(GatewayDashboardResult.id == result.id))
    ).scalar_one()
    assert promoted.dashboard_id == applied.dashboard.id
    assert promoted.version_id == applied.version.id
