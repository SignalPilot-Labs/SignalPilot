"""Deterministic connector-parity coverage for dashboard SQL dialects."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import duckdb
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.connectors.drivers.bigquery import BigQueryConnector
from gateway.connectors.drivers.clickhouse import ClickHouseConnector
from gateway.connectors.drivers.trino import TrinoConnector
from gateway.connectors.registry import (
    get_connector_registration,
    registered_connector_types,
)
from gateway.dashboard.compiler import (
    DashboardCompileError,
    compile_custom_sql_query,
    compile_distinct_values_query,
    compile_metric_query,
)
from gateway.dashboard.domain import AdHocSqlQuery, FilterRule, SemanticChartQuery
from gateway.dashboard.semantic_resolver import resolve_from_authorities
from gateway.db.models import GatewayBase
from gateway.dbt.types import ColumnSpec, ModelInfo, ModelStatus, ProjectMap
from gateway.governance.bindings import BoundQuery, BoundQueryError, ParameterStyle
from gateway.governance.plan_limits import PLAN_TIERS
from gateway.governance.query_executor import GovernedQueryContext, GovernedQueryExecutor
from gateway.models import ConnectionCreate, DBType
from gateway.models.dashboards import (
    DashboardSemanticContext,
    DashboardSemanticExplore,
    DashboardSemanticField,
    DashboardSemanticMetric,
)
from gateway.store import Store


def _context(db_type: str) -> DashboardSemanticContext:
    return DashboardSemanticContext(
        project_id="project-a",
        commit_sha="a" * 40,
        connection_name="warehouse",
        connection_type=db_type,
        physical_schema_fingerprint="physical",
        semantic_fingerprint="semantic",
        explores=[
            DashboardSemanticExplore(
                name="orders",
                label="Orders",
                relation="analytics.orders",
                dimensions=[
                    DashboardSemanticField(
                        field_id="orders.region",
                        column="select",
                        logical_type="string",
                    ),
                    DashboardSemanticField(
                        field_id="orders.ordered_at",
                        column="ordered at",
                        logical_type="timestamp",
                    ),
                ],
                metrics=[
                    DashboardSemanticMetric(
                        field_id="orders.revenue",
                        column="net revenue",
                        logical_type="number",
                        aggregation="sum",
                        label="Revenue",
                        approval_source="test",
                        human_verified=True,
                    )
                ],
            )
        ],
    )


def _metric_query() -> SemanticChartQuery:
    return SemanticChartQuery.model_validate(
        {
            "kind": "semantic",
            "projectId": "project-a",
            "commitSha": "a" * 40,
            "exploreName": "orders",
            "dimensions": ["orders.region"],
            "metrics": ["orders.revenue"],
            "filters": {
                "dimensions": {
                    "id": "all",
                    "and": [
                        {
                            "id": "region",
                            "operator": "equals",
                            "values": ["North", "South"],
                            "target": {"fieldId": "orders.region"},
                        },
                        {
                            "id": "date",
                            "operator": "inBetween",
                            "values": ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"],
                            "target": {"fieldId": "orders.ordered_at"},
                        },
                    ],
                }
            },
            "sorts": [{"fieldId": "orders.revenue", "descending": True}],
            "limit": 100,
        }
    )


EXPECTED_SQL = {
    "postgres": 'SELECT "select" AS "orders.region", SUM("net revenue") AS "orders.revenue" FROM "analytics"."orders" WHERE "select" IN ($1, $2) AND "ordered at" >= $3 AND "ordered at" < $4 GROUP BY "select" ORDER BY "orders.revenue" DESC',
    "duckdb": 'SELECT "select" AS "orders.region", SUM("net revenue") AS "orders.revenue" FROM "analytics"."orders" WHERE "select" IN (?, ?) AND "ordered at" >= ? AND "ordered at" < ? GROUP BY "select" ORDER BY "orders.revenue" DESC',
    "mysql": "SELECT `select` AS `orders.region`, SUM(`net revenue`) AS `orders.revenue` FROM `analytics`.`orders` WHERE `select` IN (%s, %s) AND `ordered at` >= %s AND `ordered at` < %s GROUP BY `select` ORDER BY `orders.revenue` DESC",
    "snowflake": 'SELECT "select" AS "orders.region", SUM("net revenue") AS "orders.revenue" FROM "analytics"."orders" WHERE "select" IN (%s, %s) AND "ordered at" >= %s AND "ordered at" < %s GROUP BY "select" ORDER BY "orders.revenue" DESC',
    "bigquery": "SELECT `select` AS `orders.region`, SUM(`net revenue`) AS `orders.revenue` FROM `analytics`.`orders` WHERE `select` IN (?, ?) AND `ordered at` >= ? AND `ordered at` < ? GROUP BY `select` ORDER BY `orders.revenue` DESC",
    "redshift": 'SELECT "select" AS "orders.region", SUM("net revenue") AS "orders.revenue" FROM "analytics"."orders" WHERE "select" IN (%s, %s) AND "ordered at" >= %s AND "ordered at" < %s GROUP BY "select" ORDER BY "orders.revenue" DESC',
    "clickhouse": "SELECT `select` AS `orders.region`, SUM(`net revenue`) AS `orders.revenue` FROM `analytics`.`orders` WHERE `select` IN (%(sp_dashboard_0)s, %(sp_dashboard_1)s) AND `ordered at` >= %(sp_dashboard_2)s AND `ordered at` < %(sp_dashboard_3)s GROUP BY `select` ORDER BY `orders.revenue` DESC",
    "databricks": "SELECT `select` AS `orders.region`, SUM(`net revenue`) AS `orders.revenue` FROM `analytics`.`orders` WHERE `select` IN (?, ?) AND `ordered at` >= ? AND `ordered at` < ? GROUP BY `select` ORDER BY `orders.revenue` DESC",
    "mssql": "SELECT [select] AS [orders.region], SUM([net revenue]) AS [orders.revenue] FROM [analytics].[orders] WHERE [select] IN (%s, %s) AND [ordered at] >= %s AND [ordered at] < %s GROUP BY [select] ORDER BY [orders.revenue] DESC",
    "trino": 'SELECT "select" AS "orders.region", SUM("net revenue") AS "orders.revenue" FROM "analytics"."orders" WHERE "select" IN (?, ?) AND "ordered at" >= ? AND "ordered at" < ? GROUP BY "select" ORDER BY "orders.revenue" DESC',
    "sqlite": 'SELECT "select" AS "orders.region", SUM("net revenue") AS "orders.revenue" FROM "analytics"."orders" WHERE "select" IN (?, ?) AND "ordered at" >= ? AND "ordered at" < ? GROUP BY "select" ORDER BY "orders.revenue" DESC',
    "xata": 'SELECT "select" AS "orders.region", SUM("net revenue") AS "orders.revenue" FROM "analytics"."orders" WHERE "select" IN ($1, $2) AND "ordered at" >= $3 AND "ordered at" < $4 GROUP BY "select" ORDER BY "orders.revenue" DESC',
}


def test_gateway_registry_has_a_complete_dashboard_contract() -> None:
    expected = {db_type.value for db_type in DBType}
    assert set(registered_connector_types()) == expected
    assert {
        db_type: get_connector_registration(db_type).dashboard_dialect.db_type
        for db_type in registered_connector_types()
    } == {db_type: db_type for db_type in registered_connector_types()}


@pytest.mark.parametrize("db_type", sorted(EXPECTED_SQL))
def test_registered_dialect_metric_sql_golden(db_type: str) -> None:
    compiled = compile_metric_query(_metric_query(), _context(db_type))
    assert compiled.sql == EXPECTED_SQL[db_type]
    assert compiled.parameters == [
        "North",
        "South",
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 2, 1, tzinfo=UTC),
    ]
    assert compiled.semantic_definition["connection_type"] == db_type


@pytest.mark.parametrize("db_type", registered_connector_types())
def test_distinct_search_and_custom_sql_keep_payloads_out_of_sql(db_type: str) -> None:
    payload = "n' OR 1=1 -- %s ? $1 :sp_dashboard_0"
    context = _context(db_type)
    distinct = compile_distinct_values_query(
        explore_name="orders",
        field_id="orders.region",
        context=context,
        search=payload,
        limit=12,
    )
    assert payload not in distinct.sql
    assert distinct.parameters == [f"%{payload}%"]
    assert " 12 " in distinct.sql or distinct.sql.endswith("LIMIT 12")

    custom = AdHocSqlQuery.model_validate(
        {
            "kind": "sql",
            "connectionName": "warehouse",
            "sqlTemplate": "SELECT 'literal :sp_dashboard_0 ? %s $1' AS note, region FROM orders;",
            "parameterDefinitions": [],
            "outputBindings": [
                {
                    "dashboardFieldId": "orders.region",
                    "outputColumn": "region",
                    "logicalType": "string",
                }
            ],
            "limit": 100,
        }
    )
    compiled = compile_custom_sql_query(
        custom,
        dialect=db_type,
        runtime_filters=[
            FilterRule.model_validate(
                {
                    "id": "region",
                    "operator": "equals",
                    "values": [payload],
                    "target": {"fieldId": "orders.region"},
                }
            )
        ],
    )
    assert payload not in compiled.sql
    assert "literal :sp_dashboard_0 ? %s $1" in compiled.sql
    assert compiled.parameters == [payload]


def test_bound_query_rejects_missing_duplicate_reordered_and_extra_tokens() -> None:
    invalid = (
        ("SELECT :sp_dashboard_0", (1, 2)),
        ("SELECT :sp_dashboard_0, :sp_dashboard_0", (1, 2)),
        ("SELECT :sp_dashboard_1, :sp_dashboard_0", (1, 2)),
        ("SELECT :sp_dashboard_0, :sp_dashboard_1", (1,)),
    )
    for sql, parameters in invalid:
        with pytest.raises(BoundQueryError):
            BoundQuery(sql, parameters, "postgres", ParameterStyle.NUMERIC_DOLLAR)


def test_bound_query_ignores_placeholder_like_text_in_literals_and_comments() -> None:
    query = BoundQuery(
        "SELECT ':sp_dashboard_0 %s ? $1' AS note -- :sp_dashboard_9\nWHERE id = :sp_dashboard_0",
        (7,),
        "postgres",
        ParameterStyle.NUMERIC_DOLLAR,
    )
    assert query.render().sql == ("SELECT ':sp_dashboard_0 %s ? $1' AS note -- :sp_dashboard_9\nWHERE id = $1")


def test_every_registered_dialect_renders_native_bindings_without_values_in_sql() -> None:
    values = ("O'Reilly", 17)
    for db_type in registered_connector_types():
        dialect = get_connector_registration(db_type).dashboard_dialect
        query = BoundQuery(
            "SELECT :sp_dashboard_0, :sp_dashboard_1",
            values,
            db_type,
            dialect.parameter_style,
        )
        rendered = query.render()
        assert values[0] not in rendered.sql
        if dialect.parameter_style == ParameterStyle.NAMED_PYFORMAT:
            assert rendered.parameters == {"sp_dashboard_0": values[0], "sp_dashboard_1": values[1]}
        else:
            assert rendered.parameters == list(values)


@pytest.mark.asyncio
async def test_bigquery_driver_creates_typed_positional_parameters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeQueryJobConfig:
        query_parameters: list[object]

    class FakeScalarQueryParameter:
        def __init__(self, name, type_name, value):
            self.name = name
            self.type_name = type_name
            self.value = value

    class FakeJob:
        total_bytes_processed = 0
        total_bytes_billed = 0
        cache_hit = False
        slot_millis = 0
        job_id = "job-1"

        def result(self, *, timeout=None):
            return [{"value": 1}]

    class FakeClient:
        def query(self, sql, *, job_config, timeout=None):
            captured.update(sql=sql, config=job_config, timeout=timeout)
            return FakeJob()

    import gateway.connectors.drivers.bigquery as bigquery_driver

    monkeypatch.setattr(
        bigquery_driver,
        "bigquery",
        SimpleNamespace(
            QueryJobConfig=FakeQueryJobConfig,
            ScalarQueryParameter=FakeScalarQueryParameter,
        ),
        raising=False,
    )
    connector = BigQueryConnector()
    connector._client = FakeClient()
    values = [True, 7, Decimal("2.50"), datetime(2026, 1, 1, tzinfo=UTC)]
    assert await connector._execute_impl("SELECT ?, ?, ?, ?", values, timeout=9) == [{"value": 1}]
    parameters = captured["config"].query_parameters
    assert [(item.name, item.type_name, item.value) for item in parameters] == [
        (None, "BOOL", values[0]),
        (None, "INT64", values[1]),
        (None, "NUMERIC", values[2]),
        (None, "TIMESTAMP", values[3]),
    ]


@pytest.mark.asyncio
async def test_trino_driver_does_not_drop_qmark_parameters() -> None:
    calls: list[tuple] = []

    class FakeCursor:
        description = [("value",)]

        def execute(self, *args):
            calls.append(args)

        def fetchall(self):
            return [(1,)]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    connector = TrinoConnector()
    connector._conn = FakeConnection()
    assert await connector._execute_impl("SELECT ?", [7]) == [{"value": 1}]
    assert calls == [("SELECT ?", [7])]


def test_clickhouse_driver_passes_named_parameters_to_native_client() -> None:
    calls: list[tuple] = []

    class FakeClient:
        def execute(self, *args, **kwargs):
            calls.append((args, kwargs))
            return [], [("value",)]

    connector = ClickHouseConnector()
    connector._client = FakeClient()
    parameters = {"sp_dashboard_0": "North"}
    connector._raw_execute("SELECT %(sp_dashboard_0)s", parameters)
    assert calls == [
        (
            ("SELECT %(sp_dashboard_0)s", parameters),
            {"with_column_types": True},
        )
    ]


def test_unknown_dashboard_dialect_fails_closed() -> None:
    with pytest.raises(DashboardCompileError, match="Unsupported dashboard connection type"):
        compile_metric_query(_metric_query(), _context("future-db"))


def test_semantic_context_uses_connection_type_in_every_registered_fingerprint() -> None:
    project_map = ProjectMap(project_name="dialects", project_dir="/immutable")
    project_map.models["orders"] = ModelInfo(
        name="orders",
        status=ModelStatus.COMPLETE,
        columns=[ColumnSpec(name="revenue", data_type="decimal")],
    )
    physical_schema = {
        "analytics.orders": {
            "schema": "analytics",
            "name": "orders",
            "columns": [{"name": "revenue", "type": "decimal"}],
        }
    }
    contexts = [
        resolve_from_authorities(
            project_id="project-a",
            commit_sha="a" * 40,
            connection_name="warehouse",
            connection_type=db_type,
            project_map=project_map,
            physical_schema=physical_schema,
            semantic_model={},
            approved_metrics=[
                {
                    "model": "orders",
                    "column": "revenue",
                    "aggregation": "sum",
                    "label": "Revenue",
                    "field_id": "orders.revenue",
                    "approval_source": "test",
                    "format": None,
                }
            ],
        )
        for db_type in registered_connector_types()
    ]
    assert [context.connection_type for context in contexts] == list(registered_connector_types())
    assert len({context.semantic_fingerprint for context in contexts}) == len(contexts)


@pytest.mark.asyncio
async def test_duckdb_dashboard_golden_path(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "dashboard.duckdb"
    setup = duckdb.connect(str(database_path))
    setup.execute("CREATE SCHEMA analytics")
    setup.execute('CREATE TABLE analytics.orders ("select" VARCHAR, "ordered at" TIMESTAMP, "net revenue" DECIMAL)')
    setup.executemany(
        "INSERT INTO analytics.orders VALUES (?, ?, ?)",
        [
            ("North", datetime(2026, 1, 3, tzinfo=UTC), 10),
            ("North", datetime(2026, 1, 4, tzinfo=UTC), 15),
            ("South", datetime(2026, 1, 5, tzinfo=UTC), 8),
            ("East", datetime(2026, 1, 6, tzinfo=UTC), 99),
        ],
    )
    setup.close()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        store = Store(session, org_id="dialect-org", user_id="dialect-user")
        await store.create_connection(
            ConnectionCreate(
                name="duckdb-dashboard",
                db_type=DBType.duckdb,
                connection_string=str(database_path),
            )
        )

        async def unlimited(_org_id: str):
            return PLAN_TIERS["unlimited"]

        monkeypatch.setattr("gateway.governance.query_executor.get_org_limits", unlimited)
        compiled = compile_metric_query(_metric_query(), _context("duckdb"))
        assert "?" in compiled.sql
        result = await GovernedQueryExecutor().execute(
            store,
            connection_name="duckdb-dashboard",
            sql=compiled.sql,
            parameters=compiled.parameters,
            bound_query=compiled.bound_query,
            row_limit=10,
            timeout_seconds=10,
            context=GovernedQueryContext(
                path="dashboard",
                project_id="project-a",
                commit_sha="a" * 40,
            ),
        )
        assert result.completeness == "complete"
        assert result.rows == [
            {"orders.region": "North", "orders.revenue": Decimal("25.000")},
            {"orders.region": "South", "orders.revenue": Decimal("8.000")},
        ]

        payload = "North' OR 1=1 --"
        distinct = compile_distinct_values_query(
            explore_name="orders",
            field_id="orders.region",
            context=_context("duckdb"),
            search=payload,
        )
        distinct_result = await GovernedQueryExecutor().execute(
            store,
            connection_name="duckdb-dashboard",
            sql=distinct.sql,
            parameters=distinct.parameters,
            bound_query=distinct.bound_query,
            row_limit=100,
            timeout_seconds=10,
            context=GovernedQueryContext(path="dashboard", project_id="project-a"),
        )
        assert distinct_result.rows == []
        assert payload not in distinct.sql

    await engine.dispose()
    assert database_path.exists()


@pytest.mark.asyncio
async def test_duckdb_file_query_cancellation_keeps_connector_usable(tmp_path) -> None:
    from gateway.connectors.drivers.duckdb import DuckDBConnector

    database_path = tmp_path / "cancel.duckdb"
    setup = duckdb.connect(str(database_path))
    setup.execute("CREATE TABLE ready AS SELECT 1 AS value")
    setup.close()

    connector = DuckDBConnector()
    await connector.connect(str(database_path))
    import asyncio

    running = asyncio.create_task(
        connector.execute(
            "SELECT SUM(a.i * b.i) FROM range(1000000000) AS a(i) CROSS JOIN range(1000000000) AS b(i)",
            timeout=30,
        )
    )
    for _ in range(100):
        if connector._active_conn is not None:
            break
        await asyncio.sleep(0.01)
    assert await connector.cancel_current_query() is True
    with pytest.raises(RuntimeError, match="DuckDB query error"):
        await running
    assert await connector.execute("SELECT value FROM ready") == [{"value": 1}]
