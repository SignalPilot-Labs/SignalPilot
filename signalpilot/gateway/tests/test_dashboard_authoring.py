"""Phase 3 typed authoring and explicit-apply contracts."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.analysis_delivery.model_client import AnthropicMessagesError, ClaudeAgentSDKStructuredClient
from gateway.api import dashboards as dashboard_api
from gateway.dashboard import store as dashboard_store
from gateway.dashboard.authoring import DashboardAgentDraft, DashboardAuthoringAgent, materialize_agent_draft
from gateway.dashboard.cache import dashboard_query_cache_key
from gateway.dashboard.domain import DashboardDefinition
from gateway.dashboard.operations import (
    DashboardTimeSeriesWindowError,
    RenameDashboard,
    apply_dashboard_operations,
    canonicalize_dashboard_explore_names,
    canonicalize_dashboard_filter_targets,
    canonicalize_dashboard_time_series_defaults,
    validate_dashboard_semantics,
    validate_time_series_default_windows,
)
from gateway.db.models import GatewayBase, GatewayDashboardAuthoringSession, GatewayDashboardResult
from gateway.models.dashboards import (
    DashboardAuthoringMessageRequest,
    DashboardAuthoringRequest,
    DashboardSemanticContext,
)

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


def _single_bar_definition(*, drill_dimensions: list[str] | None) -> DashboardDefinition:
    definition = _definition_with_filter()
    payload = definition.model_dump(mode="json", by_alias=True)
    payload["charts"] = [chart for chart in payload["charts"] if chart["id"] == "chart-bar"]
    payload["tiles"] = [tile for tile in payload["tiles"] if tile["chartId"] == "chart-bar"]
    payload["charts"][0]["signalPilot"]["drillDimensions"] = drill_dimensions
    return DashboardDefinition.model_validate(payload)


def _orders_context() -> DashboardSemanticContext:
    definition = _definition()
    return DashboardSemanticContext.model_validate(
        {
            "project_id": definition.signalPilot.projectId,
            "commit_sha": definition.signalPilot.commitSha,
            "connection_name": definition.signalPilot.connectionName,
            "connection_type": "mssql",
            "physical_schema_fingerprint": "physical",
            "semantic_fingerprint": definition.signalPilot.semanticFingerprint,
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
                        },
                        {
                            "field_id": "orders.month",
                            "column": "month",
                            "logical_type": "date",
                        },
                        {
                            "field_id": "orders.customer",
                            "column": "customer",
                            "logical_type": "string",
                        },
                        {
                            "field_id": "orders.order_date",
                            "column": "order_date",
                            "logical_type": "date",
                        },
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


async def _seed_apply_receipts(
    db: AsyncSession,
    *,
    preview,
    definition: DashboardDefinition,
    dashboard_id: str | None = None,
    version_id: str | None = None,
) -> list[GatewayDashboardResult]:
    receipt_dashboard_id = dashboard_id or preview.dashboard_id or f"draft:{preview.id}"
    receipt_version_id = version_id or f"draft:{preview.id}"
    requested_filters = [
        rule for rule in definition.filters.dimensions if rule.values or rule.operator in {"isNull", "notNull"}
    ]
    rows = []
    for chart in definition.charts:
        tile = next(tile for tile in definition.tiles if tile.chartId == chart.id)
        rows.append(
            GatewayDashboardResult(
                id=str(uuid.uuid4()),
                dashboard_id=receipt_dashboard_id,
                version_id=receipt_version_id,
                chart_id=chart.id,
                org_id="org-a",
                execution_id=f"execution-{chart.id}",
                structured_result_id=f"structured-{chart.id}",
                cache_key=dashboard_query_cache_key(
                    version_id=receipt_version_id,
                    chart=chart,
                    tile_uuid=tile.uuid,
                    requested_filters=requested_filters,
                    drill_path=[],
                    dashboard_filters=definition.filters,
                ),
                sql_hash="s" * 64,
                parameter_hash="p" * 64,
                tables_json=["dbo.orders"],
                semantic_definition_json={"chart_id": chart.id},
                completeness="complete",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
    db.add_all(rows)
    await db.commit()
    return rows


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


def test_unqualified_dashboard_filter_targets_are_canonicalized_from_their_explore() -> None:
    payload = _definition_with_filter().model_dump(mode="json", by_alias=True)
    payload["filters"]["dimensions"][0]["target"]["fieldId"] = "order_date"
    payload["filters"]["dimensions"][0]["tileTargets"] = {
        "tile-line": {"tableName": "orders", "fieldId": "month"},
        "tile-kpi": False,
    }

    canonical = canonicalize_dashboard_filter_targets(
        DashboardDefinition.model_validate(payload),
        _orders_context(),
    )

    rule = canonical.filters.dimensions[0]
    assert rule.target.fieldId == "orders.order_date"
    assert rule.tileTargets is not None
    assert rule.tileTargets["tile-line"] is not False
    assert rule.tileTargets["tile-line"].fieldId == "orders.month"
    assert rule.tileTargets["tile-kpi"] is False
    validate_dashboard_semantics(canonical, _orders_context())


def test_unknown_dashboard_filter_target_still_fails_after_canonicalization() -> None:
    payload = _definition_with_filter().model_dump(mode="json", by_alias=True)
    payload["filters"]["dimensions"][0]["target"]["fieldId"] = "missing_date"
    definition = canonicalize_dashboard_filter_targets(
        DashboardDefinition.model_validate(payload),
        _orders_context(),
    )

    with pytest.raises(ValueError, match="Unknown dashboard filter target: orders.missing_date"):
        validate_dashboard_semantics(definition, _orders_context())


def test_unknown_filter_explore_is_recovered_from_an_exact_field_id() -> None:
    payload = _definition_with_filter().model_dump(mode="json", by_alias=True)
    payload["filters"]["dimensions"][0]["target"]["tableName"] = "<UNKNOWN>"
    payload["filters"]["dimensions"][0]["tileTargets"] = {
        "tile-bar": {"tableName": "<UNKNOWN>", "fieldId": "orders.order_date"}
    }

    canonical = canonicalize_dashboard_filter_targets(
        DashboardDefinition.model_validate(payload),
        _orders_context(),
    )

    rule = canonical.filters.dimensions[0]
    assert rule.target.tableName == "orders"
    assert rule.tileTargets is not None
    assert rule.tileTargets["tile-bar"] is not False
    assert rule.tileTargets["tile-bar"].tableName == "orders"
    validate_dashboard_semantics(canonical, _orders_context())


def test_unknown_explore_is_recovered_from_exact_unambiguous_field_ids() -> None:
    payload = _single_bar_definition(drill_dimensions=["orders.customer"]).model_dump(mode="json", by_alias=True)
    payload["charts"][0]["query"]["exploreName"] = "<UNKNOWN>"

    canonical = canonicalize_dashboard_explore_names(
        DashboardDefinition.model_validate(payload),
        _orders_context(),
    )

    assert canonical.charts[0].query.exploreName == "orders"
    validate_dashboard_semantics(canonical, _orders_context())


def test_unknown_explore_is_not_recovered_from_invented_fields() -> None:
    payload = _single_bar_definition(drill_dimensions=["orders.customer"]).model_dump(mode="json", by_alias=True)
    payload["charts"][0]["query"].update({"exploreName": "<UNKNOWN>", "metrics": ["unknown.revenue"]})
    payload["charts"][0]["visualization"]["config"]["layout"]["yField"] = ["unknown.revenue"]
    definition = canonicalize_dashboard_explore_names(
        DashboardDefinition.model_validate(payload),
        _orders_context(),
    )

    assert definition.charts[0].query.exploreName == "<UNKNOWN>"
    with pytest.raises(ValueError, match="Unknown explore: <UNKNOWN>"):
        validate_dashboard_semantics(definition, _orders_context())


def test_time_series_authoring_rejects_an_empty_applicable_date_window() -> None:
    payload = _definition_with_filter().model_dump(mode="json", by_alias=True)
    payload["filters"]["dimensions"][0].update({"operator": "inBetween", "values": []})

    with pytest.raises(
        DashboardTimeSeriesWindowError,
        match="Narrow the default date window or use coarser time aggregation",
    ):
        validate_time_series_default_windows(
            DashboardDefinition.model_validate(payload),
            _orders_context(),
        )


def test_time_series_authoring_accepts_a_bounded_relative_date_window() -> None:
    validate_time_series_default_windows(_definition_with_filter(), _orders_context())


def test_time_series_authoring_canonicalizes_an_unbounded_governed_date_filter() -> None:
    payload = _definition_with_filter().model_dump(mode="json", by_alias=True)
    payload["filters"]["dimensions"][0].update({"operator": "inBetween", "values": []})

    canonical = canonicalize_dashboard_time_series_defaults(
        DashboardDefinition.model_validate(payload),
        _orders_context(),
    )

    rule = canonical.filters.dimensions[0]
    assert rule.operator == "inThePast"
    assert rule.values == [30]
    assert rule.settings is not None
    assert rule.settings.unitOfTime == "days"
    validate_time_series_default_windows(canonical, _orders_context())


@pytest.mark.parametrize(
    ("drill_dimensions", "message"),
    [
        (["orders.region"], "repeats query dimension: orders.region"),
        (["orders.customer", "orders.customer"], "repeats a drill level"),
    ],
)
def test_dashboard_semantics_rejects_duplicate_or_self_drill_levels(
    drill_dimensions: list[str],
    message: str,
) -> None:
    definition = _single_bar_definition(drill_dimensions=drill_dimensions)

    with pytest.raises(ValueError, match=message):
        validate_dashboard_semantics(definition, _orders_context())


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


class _ProviderFailingAgent:
    model = "claude-provider-test"

    def __init__(self, *, api_key: str) -> None:
        assert api_key == "test-key"

    async def draft(self, **_kwargs) -> DashboardAgentDraft:
        raise AnthropicMessagesError(
            status_code=400,
            error_type="invalid_request_error",
            provider_message="messages.0.content: Input is too long for the model context window",
            request_id="req-provider-1",
            request_body_chars=250_000,
            retry_after=None,
        )


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
        context=_orders_context(),
        base_definition=_definition_with_filter(),
    )
    materialized = materialize_agent_draft(draft, base_definition=_definition_with_filter())
    assert materialized.name == "Executive revenue"
    assert client.request is not None
    assert client.request["tool_choice"] == {"type": "tool", "name": "submit_dashboard_draft"}
    assert "question is a concise natural-language question" in client.request["system"]
    assert "never invent an explore or use placeholders" in client.request["system"]
    assert "Copy each filter target exactly" in client.request["system"]
    assert "meaningful lower-grain drill hierarchy" in client.request["system"]
    request_payload = json.loads(client.request["messages"][0]["content"])
    assert request_payload["semantic_context"]["explores"][0]["dimensions"][3]["filter_target"] == {
        "tableName": "orders",
        "fieldId": "orders.order_date",
    }
    chart_schema = client.request["tools"][0]["input_schema"]["$defs"]["ChartDefinition"]
    assert "question" in chart_schema["properties"]


def test_dashboard_authoring_uses_agent_sdk_for_oauth() -> None:
    agent = DashboardAuthoringAgent(oauth_token="oauth-token")

    assert isinstance(agent.model_client, ClaudeAgentSDKStructuredClient)
    assert agent.model_client.oauth_token == "oauth-token"
    assert agent.model_client.timeout_seconds == 240
    assert agent.model_client.use_native_structured_output is False


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
async def test_agent_allows_omitted_drills_without_a_declared_hierarchy() -> None:
    missing = _single_bar_definition(drill_dimensions=None)
    client = _ModelClient(
        {"summary": "Created the dashboard.", "definition": missing.model_dump(mode="json", by_alias=True)}
    )
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)

    draft = await agent.draft(
        prompt="Create an executive revenue dashboard",
        context=_orders_context(),
        base_definition=None,
    )

    assert draft.definition is not None
    assert draft.definition.charts[0].signalPilot.drillDimensions is None
    assert len(client.requests) == 1


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
    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_agent_repairs_semantic_validation_failures_before_returning_the_draft() -> None:
    invalid_payload = _single_bar_definition(drill_dimensions=["orders.customer"]).model_dump(
        mode="json", by_alias=True
    )
    invalid_payload["charts"][0]["query"]["exploreName"] = "sales"
    repaired = _single_bar_definition(drill_dimensions=["orders.customer"])
    client = _ModelClient(
        [
            {
                "summary": "Created the dashboard.",
                "definition": invalid_payload,
            },
            {
                "summary": "Created the dashboard with governed identifiers.",
                "definition": repaired.model_dump(mode="json", by_alias=True),
            },
        ]
    )
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)

    def validate_candidate(draft: DashboardAgentDraft) -> None:
        assert draft.definition is not None
        validate_dashboard_semantics(draft.definition, _orders_context())

    draft = await agent.draft(
        prompt="Create an executive revenue dashboard",
        context=_orders_context(),
        base_definition=None,
        validator=validate_candidate,
    )

    assert draft.definition is not None
    assert draft.definition.charts[0].query.exploreName == "orders"
    assert len(client.requests) == 2
    repair_payload = json.loads(client.requests[1]["messages"][0]["content"])
    assert "Unknown explore: sales" in repair_payload["validation_feedback"]
    assert "Valid exploreName values: orders" in repair_payload["validation_feedback"]
    assert "Never use <UNKNOWN>" in repair_payload["validation_feedback"]
    assert repair_payload["rejected_draft"]["definition"]["charts"][0]["query"]["exploreName"] == "sales"


@pytest.mark.asyncio
async def test_agent_preserves_all_validation_failures_across_repair_attempts() -> None:
    definition = _single_bar_definition(drill_dimensions=["orders.customer"])
    response = {
        "summary": "Created the dashboard.",
        "definition": definition.model_dump(mode="json", by_alias=True),
    }
    client = _ModelClient([response, response, response])
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)
    validation_attempt = 0

    def validate_candidate(_draft: DashboardAgentDraft) -> None:
        nonlocal validation_attempt
        validation_attempt += 1
        if validation_attempt == 1:
            raise ValueError("first governed validation failure")
        if validation_attempt == 2:
            raise ValueError("second governed validation failure")

    await agent.draft(
        prompt="Create an executive revenue dashboard",
        context=_orders_context(),
        base_definition=None,
        validator=validate_candidate,
    )

    final_repair_payload = json.loads(client.requests[2]["messages"][0]["content"])
    assert "first governed validation failure" in final_repair_payload["validation_feedback"]
    assert "second governed validation failure" in final_repair_payload["validation_feedback"]


@pytest.mark.asyncio
async def test_agent_repairs_invalid_tool_contract_before_returning_the_draft() -> None:
    repaired = _definition_with_filter()
    client = _ModelClient(
        [
            {
                "summary": "Returned both payload types.",
                "definition": repaired.model_dump(mode="json", by_alias=True),
                "operations": [{"operation": "rename_dashboard", "name": "Wrong mode"}],
            },
            {
                "summary": "Created one complete dashboard definition.",
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
    assert len(client.requests) == 2
    repair_payload = json.loads(client.requests[1]["messages"][0]["content"])
    assert "either a complete definition or typed operations" in repair_payload["validation_feedback"]


@pytest.mark.asyncio
async def test_agent_repairs_refusal_shaped_creation_with_mode_specific_feedback() -> None:
    repaired = _definition_with_filter()
    client = _ModelClient(
        [
            {
                "summary": "Cannot create customers because no exact customer metric is available.",
                "definition": None,
                "operations": [],
            },
            {
                "summary": "Used governed account dimensions as the closest customer representation.",
                "definition": repaired.model_dump(mode="json", by_alias=True),
            },
        ]
    )
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)

    draft = await agent.draft(
        prompt="Create an executive dashboard for revenue, margins and customers",
        context=_context(),
        base_definition=None,
    )

    assert draft.definition is not None
    assert len(client.requests) == 2
    repair_payload = json.loads(client.requests[1]["messages"][0]["content"])
    assert "refusal or empty payload" in repair_payload["validation_feedback"]
    assert "closest faithful dashboard" in repair_payload["validation_feedback"]
    assert "omit only that unsupported element" in repair_payload["validation_feedback"]


@pytest.mark.asyncio
async def test_agent_canonicalizes_unambiguous_visualization_aliases_before_contract_validation() -> None:
    payload = _definition_with_filter().model_dump(mode="json", by_alias=True)
    kpi = next(chart for chart in payload["charts"] if chart["id"] == "chart-kpi")
    kpi["visualization"]["config"] = {"field": "total_revenue", "format": "percent"}
    line = next(chart for chart in payload["charts"] if chart["id"] == "chart-line")
    line["visualization"]["config"]["layout"] = {
        "xField": "month",
        "yField": ["revenue"],
    }
    context_payload = _orders_context().model_dump(mode="json")
    context_payload["explores"][0]["metrics"][0]["format"] = "currency:USD"
    context = DashboardSemanticContext.model_validate(context_payload)
    client = _ModelClient({"summary": "Created executive dashboard.", "definition": payload})
    agent = DashboardAuthoringAgent(api_key="test", model_client=client)

    draft = await agent.draft(
        prompt="Create an executive dashboard for revenue, margins and customers",
        context=context,
        base_definition=None,
    )

    assert draft.definition is not None
    normalized_kpi = next(chart for chart in draft.definition.charts if chart.id == "chart-kpi")
    assert normalized_kpi.visualization.config.field == "orders.revenue"
    assert normalized_kpi.visualization.config.format == "currency:USD"
    normalized_line = next(chart for chart in draft.definition.charts if chart.id == "chart-line")
    assert normalized_line.visualization.config.layout.xField == "orders.month"
    assert normalized_line.visualization.config.layout.yField == ["orders.revenue"]
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_create_authoring_session_canonicalizes_model_filter_targets(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _definition_with_filter().model_dump(mode="json", by_alias=True)
    payload["filters"]["dimensions"][0]["target"]["fieldId"] = "order_date"
    model_definition = DashboardDefinition.model_validate(payload)

    class ShorthandFilterAgent:
        model = "test-model"

        def __init__(self, *, api_key: str) -> None:
            assert api_key == "test-key"

        async def draft(self, **_kwargs) -> DashboardAgentDraft:
            return DashboardAgentDraft(
                summary="Created a dashboard with a date filter.",
                definition=model_definition,
            )

    async def resolve_context(*_args, **_kwargs) -> DashboardSemanticContext:
        return _orders_context()

    async def resolve_key(*_args, **_kwargs) -> str:
        return "test-key"

    monkeypatch.setattr(dashboard_api.resolver, "resolve", resolve_context)
    monkeypatch.setattr(dashboard_api, "DashboardAuthoringAgent", ShorthandFilterAgent)
    monkeypatch.setattr(dashboard_api.org_secrets_store, "resolve_anthropic_key", resolve_key)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )

    session = await dashboard_api.create_dashboard_authoring_session(
        DashboardAuthoringRequest(
            prompt="Create an executive dashboard",
            project_id=model_definition.signalPilot.projectId,
            commit_sha=model_definition.signalPilot.commitSha,
        ),
        store,
    )

    assert session.definition.filters.dimensions[0].target.fieldId == "orders.order_date"


@pytest.mark.asyncio
async def test_create_authoring_session_force_oauth_never_resolves_org_api_key(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_definition = _definition_with_filter()

    class OAuthAuthoringAgent:
        model = "test-model"

        def __init__(self, *, oauth_token: str) -> None:
            assert oauth_token == "oauth-token"

        async def draft(self, **_kwargs) -> DashboardAgentDraft:
            return DashboardAgentDraft(
                summary="Created a dashboard using forced OAuth.",
                definition=model_definition,
            )

    async def resolve_context(*_args, **_kwargs) -> DashboardSemanticContext:
        return _orders_context()

    async def reject_org_key(*_args, **_kwargs) -> str:
        raise AssertionError("organization key must not be resolved")

    monkeypatch.setenv("SP_CHAT_FORCE_OAUTH_TOKEN", "true")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")
    monkeypatch.setattr(dashboard_api.resolver, "resolve", resolve_context)
    monkeypatch.setattr(dashboard_api, "DashboardAuthoringAgent", OAuthAuthoringAgent)
    monkeypatch.setattr(dashboard_api.org_secrets_store, "resolve_anthropic_key", reject_org_key)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )

    session = await dashboard_api.create_dashboard_authoring_session(
        DashboardAuthoringRequest(
            prompt="Create an executive dashboard",
            project_id=model_definition.signalPilot.projectId,
            commit_sha=model_definition.signalPilot.commitSha,
        ),
        store,
    )

    assert session.summary == "Created a dashboard using forced OAuth."


@pytest.mark.asyncio
async def test_dashboard_authoring_force_oauth_fails_closed_when_token_is_missing(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_org_key(*_args, **_kwargs) -> str:
        raise AssertionError("organization key must not be resolved")

    monkeypatch.setenv("SP_CHAT_FORCE_OAUTH_TOKEN", "true")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(dashboard_api.org_secrets_store, "resolve_anthropic_key", reject_org_key)
    store = SimpleNamespace(session=db_session)

    with pytest.raises(HTTPException) as exc_info:
        await dashboard_api._dashboard_authoring_agent(store, "org-a")

    assert exc_info.value.status_code == 409
    assert "no Claude OAuth token" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_create_authoring_session_returns_safe_provider_failure(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def resolve_context(*_args, **_kwargs) -> DashboardSemanticContext:
        return _orders_context()

    async def resolve_key(*_args, **_kwargs) -> str:
        return "test-key"

    monkeypatch.setattr(dashboard_api.resolver, "resolve", resolve_context)
    monkeypatch.setattr(dashboard_api, "DashboardAuthoringAgent", _ProviderFailingAgent)
    monkeypatch.setattr(dashboard_api.org_secrets_store, "resolve_anthropic_key", resolve_key)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )

    with pytest.raises(HTTPException) as exc_info:
        await dashboard_api.create_dashboard_authoring_session(
            DashboardAuthoringRequest(
                prompt="Create an executive dashboard",
                project_id="project-1",
                commit_sha="a" * 40,
            ),
            store,
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == dashboard_api._AUTHORING_PROVIDER_REJECTED
    assert "Input is too long" not in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_follow_up_provider_failure_preserves_draft_and_records_safe_message(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _definition_with_filter()
    preview = await dashboard_store.create_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=None,
        base_version_id=None,
        definition=definition,
        operations=[],
        prompt="Create a dashboard",
        summary="Created the dashboard.",
        agent_run_id="run-1",
        model="test-model",
        requires_custom_sql_confirmation=False,
        custom_sql_confirmed=False,
    )

    async def verified_context(*_args, **_kwargs) -> DashboardSemanticContext:
        return _orders_context()

    async def resolve_key(*_args, **_kwargs) -> str:
        return "test-key"

    monkeypatch.setattr(dashboard_api, "_verified_context", verified_context)
    monkeypatch.setattr(dashboard_api, "DashboardAuthoringAgent", _ProviderFailingAgent)
    monkeypatch.setattr(dashboard_api.org_secrets_store, "resolve_anthropic_key", resolve_key)
    store = SimpleNamespace(
        session=db_session,
        user_id="owner-a",
        _require_org_id=lambda: "org-a",
    )

    with pytest.raises(HTTPException) as exc_info:
        await dashboard_api.continue_dashboard_authoring_session(
            preview.id,
            DashboardAuthoringMessageRequest(prompt="Add a margin chart"),
            store,
        )

    assert exc_info.value.status_code == 502
    restored = await dashboard_store.get_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=preview.id,
    )
    assert restored is not None
    assert restored.definition_json == definition.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert restored.events_json[-1]["message"] == dashboard_api._AUTHORING_PROVIDER_REJECTED
    assert "Input is too long" not in restored.events_json[-1]["message"]


@pytest.mark.asyncio
async def test_apply_is_explicit_and_records_authoring_provenance(db_session: AsyncSession) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        definition=_definition_with_filter(),
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
    receipts = await _seed_apply_receipts(
        db_session,
        preview=preview,
        definition=definition,
    )

    applied = await dashboard_store.apply_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=preview.id,
        expected_current_version_id=created.version.id,
        visible_complete_result_ids=[row.id for row in receipts],
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
            visible_complete_result_ids=[row.id for row in receipts],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_receipt",
    ["missing", "stale", "cross_version", "cross_dashboard", "cross_org", "incomplete"],
)
async def test_apply_rejects_any_non_exact_or_incomplete_chart_receipt(
    db_session: AsyncSession,
    invalid_receipt: str,
) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        definition=_definition_with_filter(),
    )
    definition = created.version.definition.model_copy(update={"name": "Validated preview"})
    preview = await dashboard_store.create_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        base_version_id=created.version.id,
        definition=definition,
        operations=[{"operation": "rename_dashboard", "name": "Validated preview"}],
        prompt="Rename this dashboard",
        summary="Renamed the dashboard.",
        agent_run_id="agent-run-invalid-receipt",
        model="test-model",
        requires_custom_sql_confirmation=False,
        custom_sql_confirmed=False,
    )
    receipts = await _seed_apply_receipts(
        db_session,
        preview=preview,
        definition=definition,
    )
    result_ids = [row.id for row in receipts]
    if invalid_receipt == "missing":
        result_ids.pop()
    else:
        row = receipts[0]
        if invalid_receipt == "stale":
            row.cache_key = "x" * 64
        elif invalid_receipt == "cross_version":
            row.version_id = "draft:another-session"
        elif invalid_receipt == "cross_dashboard":
            row.dashboard_id = "another-dashboard"
        elif invalid_receipt == "cross_org":
            row.org_id = "org-b"
        elif invalid_receipt == "incomplete":
            row.completeness = "truncated"
        await db_session.commit()

    with pytest.raises(dashboard_store.DashboardValidationError):
        await dashboard_store.apply_authoring_session(
            db_session,
            org_id="org-a",
            user_id="owner-a",
            session_id=preview.id,
            expected_current_version_id=created.version.id,
            visible_complete_result_ids=result_ids,
        )
    unchanged = await dashboard_store.get_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
    )
    assert unchanged is not None
    assert unchanged.version.id == created.version.id


@pytest.mark.asyncio
async def test_apply_reuses_complete_base_receipts_for_unchanged_charts(
    db_session: AsyncSession,
) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        definition=_definition_with_filter(),
    )
    definition = created.version.definition.model_copy(update={"name": "Receipt reuse"})
    preview = await dashboard_store.create_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        dashboard_id=created.dashboard.id,
        base_version_id=created.version.id,
        definition=definition,
        operations=[{"operation": "rename_dashboard", "name": "Receipt reuse"}],
        prompt="Rename without changing queries",
        summary="Renamed the dashboard.",
        agent_run_id="agent-run-reuse",
        model="test-model",
        requires_custom_sql_confirmation=False,
        custom_sql_confirmed=False,
    )
    base_receipts = await _seed_apply_receipts(
        db_session,
        preview=preview,
        definition=created.version.definition,
        dashboard_id=created.dashboard.id,
        version_id=created.version.id,
    )

    applied = await dashboard_store.apply_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=preview.id,
        expected_current_version_id=created.version.id,
        visible_complete_result_ids=[row.id for row in base_receipts],
    )

    all_results = (
        (
            await db_session.execute(
                select(GatewayDashboardResult).where(GatewayDashboardResult.dashboard_id == created.dashboard.id)
            )
        )
        .scalars()
        .all()
    )
    assert {row.version_id for row in base_receipts} == {created.version.id}
    assert sum(row.version_id == applied.version.id for row in all_results) == len(definition.charts)


@pytest.mark.asyncio
async def test_applied_dashboard_reopens_the_same_authoring_thread_with_a_fresh_draft(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await dashboard_store.create_private_dashboard(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        definition=_definition_with_filter(),
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
    receipts = await _seed_apply_receipts(
        db_session,
        preview=first,
        definition=first_definition,
    )
    applied = await dashboard_store.apply_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=first.id,
        expected_current_version_id=created.version.id,
        visible_complete_result_ids=[row.id for row in receipts],
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
        return _orders_context()

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
    results = await _seed_apply_receipts(
        db_session,
        preview=preview,
        definition=preview.definition,
    )

    applied = await dashboard_store.apply_authoring_session(
        db_session,
        org_id="org-a",
        user_id="owner-a",
        session_id=preview.id,
        expected_current_version_id=None,
        visible_complete_result_ids=[result.id for result in results],
    )
    promoted = (
        (
            await db_session.execute(
                select(GatewayDashboardResult).where(GatewayDashboardResult.id.in_([result.id for result in results]))
            )
        )
        .scalars()
        .all()
    )
    assert {row.dashboard_id for row in promoted} == {applied.dashboard.id}
    assert {row.version_id for row in promoted} == {applied.version.id}
    assert {row.chart_id for row in promoted} == {chart.id for chart in applied.version.definition.charts}


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
