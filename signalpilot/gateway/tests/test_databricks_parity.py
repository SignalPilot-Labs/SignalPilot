"""Databricks connector parity tests — mocked cursors, no live warehouse.

Covers the schema introspection paths (information_schema, PK/FK attach,
DESCRIBE DETAIL metadata, small-table row-count backfill, Hive fallback),
the EXPLAIN COST→FORMATTED estimator fallback, and dialect routing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.connectors.drivers.databricks import DatabricksConnector
from gateway.governance.cost_estimator import CostEstimator


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.description = None
        self._rows: list = []

    def execute(self, sql, params=None):
        self._conn.queries.append(sql)
        handler = self._conn.route(sql)
        self._rows, self.description = handler

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakeConn:
    """Routes SQL by fragment → (rows, description)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.queries: list[str] = []

    def cursor(self):
        return _FakeCursor(self)

    def route(self, sql: str):
        for frag, result in self.routes.items():
            if frag in sql:
                return result
        return [], None


def _connector(routes: dict) -> DatabricksConnector:
    c = DatabricksConnector()
    c._conn = _FakeConn(routes)
    c._audit_sql = AsyncMock()
    return c


_DESC = [("col",)]  # unused generic description

_INFO_SCHEMA_ROUTES = {
    "FROM information_schema.columns": (
        [
            ("analytics", "orders", "order_id", "bigint", "NO", None, 1, "pk"),
            ("analytics", "orders", "amount", "decimal(18,2)", "YES", None, 2, ""),
            ("analytics", "customers", "customer_id", "bigint", "NO", None, 1, ""),
        ],
        _DESC,
    ),
    "FROM information_schema.tables": (
        [("analytics", "orders", "MANAGED"), ("analytics", "customers", "VIEW")],
        _DESC,
    ),
    "PRIMARY KEY": ([("analytics", "orders", "order_id")], _DESC),
    "FOREIGN KEY": (
        [("analytics", "orders", "customer_id", "analytics", "customers", "customer_id")],
        _DESC,
    ),
    "DESCRIBE DETAIL": (
        [(3, 42 * 1024 * 1024)],
        [("numFiles",), ("sizeInBytes",)],
    ),
    "AS tkey": ([("analytics.orders", 1234)], _DESC),
}


class TestSchemaIntrospection:
    @pytest.mark.asyncio
    async def test_information_schema_path(self):
        c = _connector(_INFO_SCHEMA_ROUTES)
        schema = await c._get_schema_impl()
        assert set(schema) == {"analytics.orders", "analytics.customers"}
        orders = schema["analytics.orders"]
        assert [col["name"] for col in orders["columns"]] == ["order_id", "amount"]
        assert orders["columns"][0]["type"] == "bigint"
        assert orders["type"] == "table"
        assert schema["analytics.customers"]["type"] == "view"

    @pytest.mark.asyncio
    async def test_primary_key_attached(self):
        c = _connector(_INFO_SCHEMA_ROUTES)
        schema = await c._get_schema_impl()
        pk_cols = [col["name"] for col in schema["analytics.orders"]["columns"] if col["primary_key"]]
        assert pk_cols == ["order_id"]

    @pytest.mark.asyncio
    async def test_foreign_key_attached(self):
        c = _connector(_INFO_SCHEMA_ROUTES)
        schema = await c._get_schema_impl()
        fks = schema["analytics.orders"]["foreign_keys"]
        assert fks == [
            {
                "column": "customer_id",
                "references_schema": "analytics",
                "references_table": "customers",
                "references_column": "customer_id",
            }
        ]

    @pytest.mark.asyncio
    async def test_describe_detail_size_metadata(self):
        c = _connector(_INFO_SCHEMA_ROUTES)
        schema = await c._get_schema_impl()
        orders = schema["analytics.orders"]
        assert orders["num_files"] == 3
        assert orders["size_mb"] == 42.0
        # views skip DESCRIBE DETAIL
        assert "size_mb" not in schema["analytics.customers"]

    @pytest.mark.asyncio
    async def test_small_table_row_count_backfilled(self):
        c = _connector(_INFO_SCHEMA_ROUTES)
        schema = await c._get_schema_impl()
        assert schema["analytics.orders"]["row_count"] == 1234

    @pytest.mark.asyncio
    async def test_large_table_row_count_not_scanned(self):
        routes = dict(_INFO_SCHEMA_ROUTES)
        routes["DESCRIBE DETAIL"] = ([(90, 500 * 1024 * 1024)], [("numFiles",), ("sizeInBytes",)])
        c = _connector(routes)
        schema = await c._get_schema_impl()
        assert schema["analytics.orders"]["row_count"] == 0  # >100MB: no COUNT(*)
        assert not any("AS tkey" in q for q in c._conn.queries)

    @pytest.mark.asyncio
    async def test_pk_fk_failures_nonfatal(self):
        routes = dict(_INFO_SCHEMA_ROUTES)
        c = _connector(routes)
        orig_route = c._conn.route

        def raising_route(sql):
            if "PRIMARY KEY" in sql or "FOREIGN KEY" in sql:
                raise RuntimeError("constraints unsupported")
            return orig_route(sql)

        c._conn.route = raising_route
        schema = await c._get_schema_impl()
        assert "analytics.orders" in schema  # still built


class TestHiveFallback:
    @pytest.mark.asyncio
    async def test_fallback_on_information_schema_failure(self):
        routes = {
            "SHOW SCHEMAS": ([("default",)], [("databaseName",)]),
            "SHOW TABLES": ([("default", "events", False)], [("database",), ("tableName",), ("isTemporary",)]),
            "DESCRIBE TABLE": (
                [("event_id", "bigint", None), ("payload", "string", None)],
                [("col_name",), ("data_type",), ("comment",)],
            ),
        }
        c = _connector(routes)
        orig_route = c._conn.route

        def raising_route(sql):
            if "information_schema" in sql:
                raise RuntimeError("no unity catalog")
            return orig_route(sql)

        c._conn.route = raising_route
        schema = await c._get_schema_impl()
        assert any("events" in k for k in schema), schema.keys()


class TestCostEstimator:
    @pytest.mark.asyncio
    async def test_explain_cost_parsed(self):
        connector = MagicMock()
        connector.execute = AsyncMock(
            return_value=[{"plan": "Statistics(sizeInBytes=1.2 MiB, rowCount=5432)"}]
        )
        est = await CostEstimator.estimate_databricks(connector, "SELECT 1")
        assert est.estimated_rows == 5432
        assert connector.execute.await_args_list[0].args[0].startswith("EXPLAIN COST")

    @pytest.mark.asyncio
    async def test_falls_back_to_formatted(self):
        connector = MagicMock()

        async def _exec(sql):
            if sql.startswith("EXPLAIN COST"):
                raise RuntimeError("COST not supported")
            return [{"plan": "numOutputRows: 77"}]

        connector.execute = AsyncMock(side_effect=_exec)
        est = await CostEstimator.estimate_databricks(connector, "SELECT 1")
        assert est.estimated_rows == 77

    @pytest.mark.asyncio
    async def test_both_explains_fail(self):
        connector = MagicMock()
        connector.execute = AsyncMock(side_effect=RuntimeError("no explain"))
        est = await CostEstimator.estimate_databricks(connector, "SELECT 1")
        assert est.warning and "no explain" in est.warning

    @pytest.mark.asyncio
    async def test_unparseable_plan_uses_conservative_default(self):
        connector = MagicMock()
        connector.execute = AsyncMock(return_value=[{"plan": "opaque plan text"}])
        est = await CostEstimator.estimate_databricks(connector, "SELECT 1")
        assert est.estimated_rows == 10000


class TestDialectRouting:
    def test_approx_distinct_for_databricks(self):
        # model_map imports the MCP server (unimportable in this local env);
        # assert the dialect mapping at source level instead.
        import pathlib

        src = pathlib.Path("gateway/mcp/tools/model_map.py").read_text(encoding="utf-8")
        assert '"databricks": "APPROX_COUNT_DISTINCT"' in src

    def test_identifier_quote_backtick(self):
        assert DatabricksConnector()._identifier_quote == "`"


class TestBackfillEdgeCases:
    async def test_null_size_excluded_from_count_backfill(self):
        """Non-Delta tables report NULL sizeInBytes — must not be COUNT(*)-scanned."""
        routes = dict(_INFO_SCHEMA_ROUTES)
        routes["DESCRIBE DETAIL"] = ([(None, None)], [("numFiles",), ("sizeInBytes",)])
        c = _connector(routes)
        schema = await c._get_schema_impl()
        assert "size_mb" not in schema["analytics.orders"]
        assert schema["analytics.orders"]["row_count"] == 0
        assert not any("AS tkey" in q for q in c._conn.queries)

    async def test_count_batch_failure_keeps_schema(self):
        c = _connector(_INFO_SCHEMA_ROUTES)
        orig_route = c._conn.route

        def raising_route(sql):
            if "AS tkey" in sql:
                raise RuntimeError("no SELECT privilege")
            return orig_route(sql)

        c._conn.route = raising_route
        schema = await c._get_schema_impl()
        assert schema["analytics.orders"]["row_count"] == 0
        assert schema["analytics.orders"]["size_mb"] == 42.0  # metadata intact

    async def test_detail_extras_captured(self):
        routes = dict(_INFO_SCHEMA_ROUTES)
        routes["DESCRIBE DETAIL"] = (
            [(3, 42 * 1024 * 1024, ["region"], ["order_id"], "2026-07-01 00:00:00")],
            [("numFiles",), ("sizeInBytes",), ("partitionColumns",), ("clusteringColumns",), ("lastModified",)],
        )
        c = _connector(routes)
        schema = await c._get_schema_impl()
        t = schema["analytics.orders"]
        assert t["partition_columns"] == ["region"]
        assert t["clustering_columns"] == ["order_id"]
        assert t["last_modified"].startswith("2026-07-01")


class TestEstimatorScientificNotation:
    async def test_scientific_notation_rowcount(self):
        """Spark prints rowCount past 3 sig figs as e.g. 5.43E+3."""
        connector = MagicMock()
        connector.execute = AsyncMock(
            return_value=[{"plan": "Statistics(sizeInBytes=1.2 GiB, rowCount=5.43E+3)"}]
        )
        est = await CostEstimator.estimate_databricks(connector, "SELECT 1")
        assert est.estimated_rows == 5430

    async def test_failure_warning_includes_cause(self):
        connector = MagicMock()
        connector.execute = AsyncMock(side_effect=RuntimeError("permission denied on table x"))
        est = await CostEstimator.estimate_databricks(connector, "SELECT 1")
        assert "permission denied" in (est.warning or "")
