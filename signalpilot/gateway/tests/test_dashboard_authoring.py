"""Phase 3 typed authoring and explicit-apply contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.api import dashboards as dashboard_api
from gateway.dashboard import store as dashboard_store
from gateway.dashboard.authoring import DashboardAgentDraft, DashboardAuthoringAgent, materialize_agent_draft
from gateway.dashboard.domain import DashboardDefinition
from gateway.dashboard.operations import RenameDashboard, apply_dashboard_operations
from gateway.db.models import GatewayBase, GatewayDashboardAuthoringSession, GatewayDashboardResult
from gateway.models.dashboards import DashboardAuthoringMessageRequest, DashboardSemanticContext

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


def _definition_with_filter() -> DashboardDefinition:
    definition = _definition()
    rule = {
        "id": "date-filter",
        "operator": "inThePast",
        "values": [30],
        "target": {"tableName": "orders", "fieldId": "orders.order_date"},
        "label": "Order date",
        "settings": {"unitOfTime": "days"},
    }
    payload = definition.model_dump(mode="json", by_alias=True)
    payload["filters"]["dimensions"] = [rule]
    return DashboardDefinition.model_validate(payload)


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
    def __init__(self, payload: dict | list[dict]) -> None:
        self.payloads = payload if isinstance(payload, list) else [payload]
        self.request: dict | None = None
        self.requests: list[dict] = []

    async def create_message(self, request_body: dict) -> dict:
        self.request = request_body
        self.requests.append(request_body)
        payload = self.payloads[min(len(self.requests) - 1, len(self.payloads) - 1)]
        return {
            "content": [
                {
                    "type": "tool_use",
                    "name": "submit_dashboard_draft",
                    "input": payload,
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
        base_definition=_definition_with_filter(),
    )
    materialized = materialize_agent_draft(draft, base_definition=_definition_with_filter())
    assert materialized.name == "Executive revenue"
    assert client.request is not None
    assert client.request["tool_choice"] == {"type": "tool", "name": "submit_dashboard_draft"}
    assert "question is a concise natural-language question" in client.request["system"]
    chart_schema = client.request["tools"][0]["input_schema"]["$defs"]["ChartDefinition"]
    assert "question" in chart_schema["properties"]


@pytest.mark.asyncio
async def test_agent_repairs_filterless_creation_before_returning_the_draft() -> None:
    empty = _definition()
    repaired = _definition_with_filter()
    client = _ModelClient(
        [
            {"summary": "Created the dashboard.", "definition": empty.model_dump(mode="json", by_alias=True)},
            {
                "summary": "Created the dashboard with filters.",
                "definition": repaired.model_dump(mode="json", by_alias=True),
            },
        ]
    )
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)
    draft = await agent.draft(
        prompt="Create an executive revenue dashboard",
        context=_context(),
        base_definition=None,
    )
    assert draft.definition is not None
    assert [rule.id for rule in draft.definition.filters.dimensions] == ["date-filter"]
    assert len(client.requests) == 2
    repair_payload = json.loads(client.requests[1]["messages"][0]["content"])
    assert "validation_feedback" in repair_payload
    assert "rejected_draft" in repair_payload


@pytest.mark.asyncio
async def test_agent_repairs_filterless_follow_up_with_typed_filter_operation() -> None:
    filter_operation = {
        "operation": "add_filter_control",
        "filter": _definition_with_filter().filters.dimensions[0].model_dump(mode="json", by_alias=True),
    }
    client = _ModelClient(
        [
            {
                "summary": "Renamed the dashboard.",
                "operations": [{"operation": "rename_dashboard", "name": "Executive revenue"}],
            },
            {
                "summary": "Renamed the dashboard and added a date filter.",
                "operations": [
                    {"operation": "rename_dashboard", "name": "Executive revenue"},
                    filter_operation,
                ],
            },
        ]
    )
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)
    draft = await agent.draft(
        prompt="Rename this dashboard",
        context=_context(),
        base_definition=_definition(),
    )
    materialized = materialize_agent_draft(draft, base_definition=_definition())
    assert materialized.name == "Executive revenue"
    assert [rule.id for rule in materialized.filters.dimensions] == ["date-filter"]
    assert len(client.requests) == 2


@pytest.mark.asyncio
async def test_explicit_filter_opt_out_allows_a_filterless_draft() -> None:
    empty = _definition()
    client = _ModelClient(
        {
            "summary": "Created the dashboard without filters.",
            "definition": empty.model_dump(mode="json", by_alias=True),
        }
    )
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)
    draft = await agent.draft(
        prompt="Create an executive revenue dashboard without filters",
        context=_context(),
        base_definition=None,
    )
    assert draft.definition is not None
    assert draft.definition.filters.dimensions == []
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_agent_rejects_a_second_filterless_response() -> None:
    empty = _definition()
    client = _ModelClient(
        {"summary": "Created the dashboard.", "definition": empty.model_dump(mode="json", by_alias=True)}
    )
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)
    with pytest.raises(ValueError, match="requires at least one governed filter control"):
        await agent.draft(
            prompt="Create an executive revenue dashboard",
            context=_context(),
            base_definition=None,
        )
    assert len(client.requests) == 2


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
    with pytest.raises(dashboard_store.DashboardValidationError):
        await dashboard_store.apply_authoring_session(
            db_session,
            org_id="org-a",
            user_id="owner-a",
            session_id=preview.id,
            expected_current_version_id=created.version.id,
            visible_complete_result_ids=[],
        )


@pytest.mark.asyncio
async def test_applied_dashboard_reopens_the_same_authoring_thread_with_a_fresh_draft(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        definition=_definition(),
    )
    first_definition = created.version.definition.model_copy(update={"name": "First edit"})
    first = await dashboard_store.create_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        base_version_id=created.version.id,
        definition=first_definition,
        operations=[{"operation": "rename_dashboard", "name": "First edit"}],
        prompt="Rename the dashboard",
        summary="Renamed the dashboard.",
        agent_run_id="run-1",
        model="test-model",
        requires_custom_sql_confirmation=False,
        custom_sql_confirmed=False,
    )
    applied = await dashboard_store.apply_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=first.id,
        expected_current_version_id=created.version.id,
        visible_complete_result_ids=[],
    )
    reopened = await dashboard_store.get_active_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
    )
    assert reopened is not None
    assert reopened.status == "applied"
    assert reopened.events_json[-1]["message"] == "Applied dashboard version 2"

    class ResumedAgent:
        model = "test-model"

        def __init__(self, *, api_key: str) -> None:
            assert api_key == "test-key"

        async def draft(self, **_kwargs) -> DashboardAgentDraft:
            return DashboardAgentDraft(
                summary="Renamed the dashboard again.",
                operations=[RenameDashboard(operation="rename_dashboard", name="Second edit")],
            )

    async def verified_context(*_args, **_kwargs) -> DashboardSemanticContext:
        return _context()

    async def resolve_key(*_args, **_kwargs) -> str:
        return "test-key"

    monkeypatch.setattr(dashboard_api, "DashboardAuthoringAgent", ResumedAgent)
    monkeypatch.setattr(dashboard_api, "_verified_context", verified_context)
    monkeypatch.setattr(dashboard_api, "validate_dashboard_semantics", lambda *_args: None)
    monkeypatch.setattr(dashboard_api.org_secrets_store, "resolve_anthropic_key", resolve_key)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )
    second = await dashboard_api.continue_dashboard_authoring_session(
        first.id,
        DashboardAuthoringMessageRequest(prompt="Rename it again"),
        store,
    )
    assert second.id != first.id
    assert second.thread_id == first.thread_id
    assert second.base_version_id == applied.version.id
    assert second.definition.name == "Second edit"
    assert [event.kind for event in second.events].count("user") == 2
    assert [event.kind for event in second.events].count("assistant") == 2
    assert any("latest saved dashboard version" in event.message for event in second.events)


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


@pytest.mark.asyncio
async def test_follow_up_updates_the_current_unsaved_draft_and_preserves_conversation(
    db_session: AsyncSession,
) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session, org_id="org-a", user_id="owner-a", definition=_definition()
    )
    first_definition = created.version.definition.model_copy(update={"name": "First unsaved name"})
    preview = await dashboard_store.create_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        base_version_id=created.version.id,
        definition=first_definition,
        operations=[{"operation": "rename_dashboard", "name": "First unsaved name"}],
        prompt="Rename it once",
        summary="Renamed the dashboard.",
        agent_run_id="run-1",
        model="test-model",
        requires_custom_sql_confirmation=False,
        custom_sql_confirmed=False,
    )
    second_definition = first_definition.model_copy(update={"description": "Keep both unsaved changes."})
    updated = await dashboard_store.update_authoring_session_draft(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=preview.id,
        definition=second_definition,
        operations=[{"operation": "describe_dashboard", "description": "Keep both unsaved changes."}],
        prompt="Now update the description",
        summary="Updated the description.",
        agent_run_id="run-2",
        model="test-model",
        requires_custom_sql_confirmation=False,
        pending_custom_sql_chart_ids=[],
    )
    assert updated.definition.name == "First unsaved name"
    assert updated.definition.description == "Keep both unsaved changes."
    assert updated.draft_revision == 2
    assert [event.kind for event in updated.events].count("user") == 2
    assert [event.kind for event in updated.events].count("assistant") == 2
    assert (
        await dashboard_store.get_authoring_session(
            db_session,
            org_id="org-a",
            user_id="viewer-a",
            session_id=preview.id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_failed_follow_up_retains_last_valid_draft_and_discard_creates_no_version(
    db_session: AsyncSession,
) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session, org_id="org-a", user_id="owner-a", definition=_definition()
    )
    preview = await dashboard_store.create_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        base_version_id=created.version.id,
        definition=created.version.definition,
        operations=[],
        prompt="Keep this draft",
        summary="Kept the dashboard.",
        agent_run_id="run-1",
        model="test-model",
        requires_custom_sql_confirmation=False,
        custom_sql_confirmed=False,
    )
    await dashboard_store.record_authoring_failure(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=preview.id,
        prompt="Use a metric that does not exist",
        safe_message="That metric is not approved.",
    )
    restored = await dashboard_store.get_authoring_session(
        db_session, org_id="org-a", user_id="owner-a", session_id=preview.id
    )
    assert restored is not None
    assert restored.definition_json == preview.definition.model_dump(mode="json", by_alias=True, exclude_none=True)
    discarded = await dashboard_store.discard_authoring_session(
        db_session, org_id="org-a", user_id="owner-a", session_id=preview.id
    )
    assert discarded.status == "discarded"
    assert created.dashboard.current_version_id == created.version.id
    sessions = (await db_session.execute(select(GatewayDashboardAuthoringSession))).scalars().all()
    assert len(sessions) == 1
