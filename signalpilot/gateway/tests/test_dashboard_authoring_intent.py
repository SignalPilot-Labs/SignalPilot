"""Creation intent schema and deterministic compiler coverage."""

from __future__ import annotations

import json

import pytest

from gateway.dashboard.authoring_intent import (
    DashboardChartIntent,
    DashboardCreationIntent,
    DashboardFilterIntent,
    DashboardIntentValidationError,
    compile_dashboard_creation_intent,
)
from gateway.dashboard.operations import validate_dashboard_semantics, validate_time_series_default_windows
from gateway.models.dashboards import DashboardSemanticContext


def _context() -> DashboardSemanticContext:
    return DashboardSemanticContext.model_validate(
        {
            "project_id": "project-1",
            "commit_sha": "b91bd2273f38fdc58702c71f538b6b5d5ae462c5",
            "connection_name": "mssql-pilot",
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
                            "field_id": "orders.month",
                            "column": "month",
                            "logical_type": "date",
                            "label": "Month",
                        },
                        {
                            "field_id": "orders.region",
                            "column": "region",
                            "logical_type": "string",
                            "label": "Region",
                        },
                    ],
                    "metrics": [
                        {
                            "field_id": "orders.revenue",
                            "column": "revenue",
                            "logical_type": "number",
                            "label": "Revenue",
                            "aggregation": "sum",
                            "format": "currency:USD",
                            "approval_source": "test",
                            "human_verified": True,
                        },
                        {
                            "field_id": "orders.margin",
                            "column": "margin",
                            "logical_type": "number",
                            "label": "Margin",
                            "aggregation": "average",
                            "format": "percent",
                            "approval_source": "test",
                            "human_verified": True,
                        },
                    ],
                },
                {
                    "name": "customers",
                    "label": "Customers",
                    "relation": "dbo.customers",
                    "dimensions": [
                        {
                            "field_id": "customers.created_month",
                            "column": "created_month",
                            "logical_type": "date",
                        },
                        {
                            "field_id": "customers.segment",
                            "column": "segment",
                            "logical_type": "string",
                        },
                    ],
                    "metrics": [
                        {
                            "field_id": "customers.count",
                            "column": "customer_id",
                            "logical_type": "number",
                            "label": "Customers",
                            "aggregation": "count_distinct",
                            "format": "number",
                            "approval_source": "test",
                            "human_verified": True,
                        }
                    ],
                },
            ],
        }
    )


def _intent() -> DashboardCreationIntent:
    return DashboardCreationIntent(
        summary="Created an executive overview.",
        name="Executive Overview",
        description="Revenue, margin, and customer health.",
        charts=[
            DashboardChartIntent(
                ref="revenue",
                visualization="kpi",
                exploreName="orders",
                metrics=["orders.revenue"],
                title="Total Revenue",
                question="What is total revenue",
                description="Current governed revenue.",
            ),
            DashboardChartIntent(
                ref="margin",
                visualization="kpi",
                exploreName="orders",
                metrics=["orders.margin"],
                title="Gross Margin",
                question="What is gross margin?",
                description="Current governed margin.",
            ),
            DashboardChartIntent(
                ref="customers",
                visualization="kpi",
                exploreName="customers",
                metrics=["customers.count"],
                title="Customers",
                question="How many customers are there?",
                description="Current governed customer count.",
            ),
            DashboardChartIntent(
                ref="revenue-trend",
                visualization="line",
                exploreName="orders",
                dimensions=["orders.month"],
                metrics=["orders.revenue"],
                title="Revenue Trend",
                question="How is revenue changing?",
                description="Line chart showing revenue over time.",
            ),
        ],
        filters=[DashboardFilterIntent(exploreName="orders", fieldId="orders.region")],
    )


def test_creation_intent_schema_excludes_dashboard_mechanics_and_sql() -> None:
    schema = json.dumps(DashboardCreationIntent.model_json_schema(by_alias=True))

    for forbidden in (
        "sqlTemplate",
        "outputBindings",
        "xField",
        "yField",
        "tileTargets",
        "signalPilot",
        "commitSha",
        "format",
    ):
        assert forbidden not in schema


def test_compiler_generates_valid_definition_with_formats_layout_and_filters() -> None:
    definition = compile_dashboard_creation_intent(_intent(), _context(), timezone="America/New_York")

    assert [tile.w for tile in definition.tiles[:3]] == [12, 12, 12]
    assert [tile.x for tile in definition.tiles[:3]] == [0, 12, 24]
    assert definition.tiles[3].w == 36
    assert definition.tiles[3].y == 5
    revenue, margin, customers, trend = definition.charts
    assert revenue.visualization.config.field == "orders.revenue"
    assert revenue.visualization.config.format == "currency:USD"
    assert margin.visualization.config.format == "percentage"
    assert customers.visualization.config.format == "decimal"
    assert trend.visualization.config.layout.xField == "orders.month"
    assert trend.visualization.config.layout.yField == ["orders.revenue"]
    assert revenue.question == "What is total revenue?"
    assert definition.signalPilot.timezone == "America/New_York"
    date_filter, region_filter = definition.filters.dimensions
    assert date_filter.target.fieldId == "orders.month"
    assert date_filter.operator == "inThePast"
    assert date_filter.values == [30]
    assert date_filter.tileTargets is not None
    assert date_filter.tileTargets[definition.tiles[2].uuid] is False
    assert region_filter.target.fieldId == "orders.region"
    validate_dashboard_semantics(definition, _context())
    validate_time_series_default_windows(definition, _context())


def test_compiler_is_deterministic_for_the_same_intent() -> None:
    first = compile_dashboard_creation_intent(_intent(), _context(), timezone="UTC")
    second = compile_dashboard_creation_intent(_intent(), _context(), timezone="UTC")

    assert first == second


def test_compiler_returns_structured_unknown_metric_feedback() -> None:
    intent = _intent().model_copy(deep=True)
    intent.charts[0].metrics = ["orders.total_revenue"]

    with pytest.raises(DashboardIntentValidationError) as error:
        compile_dashboard_creation_intent(intent, _context(), timezone="UTC")

    issue = error.value.as_payload()[0]
    assert issue == {
        "code": "unknown_metric",
        "path": "charts[0].metrics[0]",
        "message": "Unknown metric for orders: orders.total_revenue",
        "rejectedValue": "orders.total_revenue",
        "allowedValues": ["orders.revenue", "orders.margin"],
    }


def test_compiler_rejects_duplicate_chart_refs_before_generating_ids() -> None:
    intent = _intent().model_copy(deep=True)
    intent.charts[1].ref = intent.charts[0].ref

    with pytest.raises(DashboardIntentValidationError) as error:
        compile_dashboard_creation_intent(intent, _context(), timezone="UTC")

    assert error.value.as_payload()[0]["code"] == "duplicate_chart_ref"


def test_filter_opt_out_uses_private_bounded_query_window_for_time_series() -> None:
    definition = compile_dashboard_creation_intent(
        _intent(),
        _context(),
        timezone="UTC",
        include_filters=False,
    )

    assert definition.filters.dimensions == []
    trend = definition.charts[3]
    assert trend.query.filters.dimensions is not None
    rule = trend.query.filters.dimensions.and_[0]
    assert rule.operator == "inThePast"
    assert rule.values == [30]
    validate_time_series_default_windows(definition, _context())
