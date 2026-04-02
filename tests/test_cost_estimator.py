"""Tests for query cost estimation — Feature #13."""

import pytest

from signalpilot.gateway.gateway.governance.cost_estimator import (
    CostEstimate,
    CostEstimator,
    _COST_PER_ROW,
)

_POSTGRES_USD_PER_ROW = _COST_PER_ROW["postgres"]


class TestCostEstimate:
    """Tests for the CostEstimate dataclass."""

    def test_default_values(self):
        est = CostEstimate()
        assert est.estimated_rows == 0
        assert est.estimated_usd == 0.0
        assert est.is_expensive is False
        assert est.warning is None

    def test_is_expensive_by_usd(self):
        est = CostEstimate(estimated_usd=1.5)
        assert est.is_expensive is True

    def test_is_expensive_by_rows(self):
        est = CostEstimate(estimated_rows=2_000_000)
        assert est.is_expensive is True

    def test_not_expensive_under_threshold(self):
        est = CostEstimate(estimated_rows=500, estimated_usd=0.001)
        assert est.is_expensive is False

    def test_expensive_exactly_at_threshold(self):
        est = CostEstimate(estimated_rows=1_000_001)
        assert est.is_expensive is True

    def test_usd_threshold_boundary(self):
        est = CostEstimate(estimated_usd=0.99)
        assert est.is_expensive is False
        est2 = CostEstimate(estimated_usd=1.01)
        assert est2.is_expensive is True

    def test_with_warning(self):
        est = CostEstimate(warning="EXPLAIN returned no data")
        assert est.warning == "EXPLAIN returned no data"
        assert est.is_expensive is False

    def test_raw_plan(self):
        est = CostEstimate(raw_plan='[{"Plan": {"Total Cost": 100}}]')
        assert est.raw_plan is not None
        assert "Total Cost" in est.raw_plan


class TestCostEstimatorRouting:
    """Tests for CostEstimator.estimate() routing logic."""

    @pytest.mark.asyncio
    async def test_unsupported_db_type(self):
        """Unsupported databases should return a warning, not an error."""
        est = await CostEstimator.estimate(None, "SELECT 1", "mongodb")  # type: ignore
        assert est.warning is not None
        assert "not supported" in est.warning

    @pytest.mark.asyncio
    async def test_unsupported_snowflake(self):
        est = await CostEstimator.estimate(None, "SELECT 1", "snowflake")  # type: ignore
        assert est.warning is not None


class TestAllDBTypesHavePricing:
    """All supported DB types should have cost-per-row entries."""

    def test_all_types_present(self):
        expected = ["postgres", "redshift", "mysql", "snowflake", "bigquery",
                    "clickhouse", "databricks", "duckdb", "sqlite", "mssql", "trino"]
        for db_type in expected:
            assert db_type in _COST_PER_ROW, f"{db_type} missing from _COST_PER_ROW"

    def test_bigquery_2026_pricing(self):
        """BigQuery should use 2026 pricing of $6.25/TB."""
        assert _COST_PER_ROW["bigquery"] == 0.000_006_25

    def test_local_dbs_are_free(self):
        assert _COST_PER_ROW["duckdb"] == 0.0
        assert _COST_PER_ROW["sqlite"] == 0.0

    def test_warehouses_more_expensive_than_rdbms(self):
        assert _COST_PER_ROW["snowflake"] > _COST_PER_ROW["postgres"]
        assert _COST_PER_ROW["bigquery"] > _COST_PER_ROW["mysql"]


class TestCostEstimatorMethods:
    """All estimator static methods should exist."""

    def test_all_estimators_exist(self):
        methods = ["estimate_postgres", "estimate_mysql", "estimate_snowflake",
                   "estimate_bigquery", "estimate_redshift", "estimate_clickhouse",
                   "estimate_databricks", "estimate_duckdb", "estimate_mssql",
                   "estimate_trino"]
        for method in methods:
            assert hasattr(CostEstimator, method), f"Missing estimator: {method}"


class TestPostgresCostConstants:
    """Test cost calculation constants."""

    def test_postgres_usd_per_row_reasonable(self):
        """Verify the per-row cost constant is in a reasonable range."""
        assert 0 < _POSTGRES_USD_PER_ROW < 0.001
        # 1M rows should cost less than $1 (the expensive threshold)
        assert 1_000_000 * _POSTGRES_USD_PER_ROW < 1.0
        # 10M rows should trigger expensive threshold
        assert 10_000_000 * _POSTGRES_USD_PER_ROW > 1.0

    def test_cost_formula(self):
        """Test the USD estimation formula directly."""
        rows = 100_000
        expected_usd = rows * _POSTGRES_USD_PER_ROW
        est = CostEstimate(estimated_rows=rows, estimated_usd=expected_usd)
        assert est.estimated_usd == pytest.approx(0.03, rel=0.1)
        assert est.is_expensive is False


# --- Mock-connector-based EXPLAIN parsing tests ---

import json


class _FakeConnector:
    """Minimal mock connector for CostEstimator tests."""

    def __init__(self, rows=None, error=None):
        self._rows = rows or []
        self._error = error
        self.calls: list[str] = []

    async def execute(self, sql, *args, **kwargs):
        self.calls.append(sql)
        if self._error:
            raise self._error
        return self._rows


class TestPostgresExplainParsing:
    """Test Postgres EXPLAIN JSON parsing."""

    @pytest.mark.asyncio
    async def test_json_plan_string(self):
        plan = [{"Plan": {"Total Cost": 42.5, "Plan Rows": 1000}}]
        conn = _FakeConnector(rows=[{"QUERY PLAN": json.dumps(plan)}])
        result = await CostEstimator.estimate_postgres(conn, "SELECT 1")
        assert result.estimated_rows == 1000
        assert result.estimated_cost == 42.5
        assert result.estimated_usd == pytest.approx(1000 * _COST_PER_ROW["postgres"])
        assert result.warning is None

    @pytest.mark.asyncio
    async def test_json_plan_list(self):
        """Some drivers return the plan as a list directly, not a JSON string."""
        plan = [{"Plan": {"Total Cost": 10.0, "Plan Rows": 500}}]
        conn = _FakeConnector(rows=[{"col": plan}])
        result = await CostEstimator.estimate_postgres(conn, "SELECT 1")
        assert result.estimated_rows == 500

    @pytest.mark.asyncio
    async def test_empty_explain(self):
        conn = _FakeConnector(rows=[])
        result = await CostEstimator.estimate_postgres(conn, "SELECT 1")
        assert result.warning is not None

    @pytest.mark.asyncio
    async def test_error_returns_warning(self):
        conn = _FakeConnector(error=Exception("connection lost"))
        result = await CostEstimator.estimate_postgres(conn, "SELECT 1")
        assert "connection lost" in result.warning


class TestMySQLExplainParsing:
    """Test MySQL EXPLAIN FORMAT=JSON parsing."""

    @pytest.mark.asyncio
    async def test_parses_explain_json(self):
        plan = json.dumps({
            "query_block": {
                "cost_info": {"query_cost": "15.30"},
                "table": {"rows_examined_per_scan": 2000},
            }
        })
        conn = _FakeConnector(rows=[{"EXPLAIN": plan}])
        result = await CostEstimator.estimate_mysql(conn, "SELECT 1")
        assert result.estimated_rows == 2000
        assert result.estimated_cost == pytest.approx(15.30)
        assert result.estimated_usd == pytest.approx(2000 * _COST_PER_ROW["mysql"])

    @pytest.mark.asyncio
    async def test_empty_table_block(self):
        plan = json.dumps({"query_block": {"cost_info": {"query_cost": "0"}}})
        conn = _FakeConnector(rows=[{"EXPLAIN": plan}])
        result = await CostEstimator.estimate_mysql(conn, "SELECT 1")
        assert result.estimated_rows == 0


class TestMSSQLExplainParsing:
    """Test MSSQL SET SHOWPLAN_ALL parsing."""

    @pytest.mark.asyncio
    async def test_parses_showplan(self):
        showplan_rows = [
            {"EstimateRows": 5000, "TotalSubtreeCost": 0.5, "StmtText": "Clustered Index Scan"},
            {"EstimateRows": 100, "TotalSubtreeCost": 0.1, "StmtText": "Hash Match"},
        ]
        call_idx = 0

        class _MSSQLMock:
            async def execute(self, sql, *a, **kw):
                nonlocal call_idx
                call_idx += 1
                if call_idx == 2:  # The actual query (between SET ON and SET OFF)
                    return showplan_rows
                return []

        result = await CostEstimator.estimate_mssql(_MSSQLMock(), "SELECT 1")
        assert result.estimated_rows == 5000
        assert result.estimated_cost == pytest.approx(0.5)


class TestClickHouseExplainParsing:
    """Test ClickHouse EXPLAIN ESTIMATE and EXPLAIN PLAN parsing."""

    @pytest.mark.asyncio
    async def test_explain_estimate(self):
        rows = [
            {"database": "default", "table": "events", "parts": 3, "rows": 100000, "marks": 50},
        ]
        conn = _FakeConnector(rows=rows)
        result = await CostEstimator.estimate_clickhouse(conn, "SELECT 1")
        assert result.estimated_rows == 100000
        assert result.estimated_usd == pytest.approx(100000 * _COST_PER_ROW["clickhouse"])

    @pytest.mark.asyncio
    async def test_fallback_to_explain_plan(self):
        """If EXPLAIN ESTIMATE fails, falls back to EXPLAIN PLAN."""
        call_idx = 0

        class _CHFallback:
            async def execute(self, sql, *a, **kw):
                nonlocal call_idx
                call_idx += 1
                if "ESTIMATE" in sql:
                    raise Exception("not supported")
                return [{"explain": "ReadFromMergeTree rows: 50000"}]

        result = await CostEstimator.estimate_clickhouse(_CHFallback(), "SELECT 1")
        assert result.estimated_rows == 50000


class TestRedshiftExplainParsing:
    """Test Redshift text-based EXPLAIN parsing."""

    @pytest.mark.asyncio
    async def test_parses_rows(self):
        rows = [
            {"QUERY PLAN": "XN Seq Scan on users  (cost=0.00..5.00 rows=500 width=100)"},
            {"QUERY PLAN": "  ->  XN Hash Join  (cost=0.10..10.00 rows=1000 width=200)"},
        ]
        conn = _FakeConnector(rows=rows)
        result = await CostEstimator.estimate_redshift(conn, "SELECT 1")
        assert result.estimated_rows == 1000  # max of 500 and 1000

    @pytest.mark.asyncio
    async def test_no_rows_in_plan(self):
        rows = [{"QUERY PLAN": "Result  (cost=0.00..0.01 width=0)"}]
        conn = _FakeConnector(rows=rows)
        result = await CostEstimator.estimate_redshift(conn, "SELECT 1")
        assert result.estimated_rows == 0


class TestTrinoExplainParsing:
    """Test Trino EXPLAIN parsing."""

    @pytest.mark.asyncio
    async def test_parses_rows(self):
        rows = [
            {"Query Plan": "Fragment 0 [SINGLE] est. 2500 rows"},
            {"Query Plan": "  TableScan rows: 5000"},
        ]
        conn = _FakeConnector(rows=rows)
        result = await CostEstimator.estimate_trino(conn, "SELECT 1")
        assert result.estimated_rows == 5000


class TestDuckDBEstimator:
    """Test DuckDB cost estimation (always free)."""

    @pytest.mark.asyncio
    async def test_local_is_free(self):
        conn = _FakeConnector(rows=[{"explain_value": "SCAN TABLE t"}])
        result = await CostEstimator.estimate_duckdb(conn, "SELECT 1")
        assert result.estimated_usd == 0.0
        assert result.estimated_rows == 0


class TestEstimateRouting:
    """Test that estimate() routes to the correct estimator."""

    @pytest.mark.asyncio
    async def test_sqlite_routes_to_duckdb(self):
        conn = _FakeConnector(rows=[{"explain_value": "SCAN"}])
        result = await CostEstimator.estimate(conn, "SELECT 1", "sqlite")
        assert result.estimated_usd == 0.0

    @pytest.mark.asyncio
    async def test_unknown_db_returns_warning(self):
        result = await CostEstimator.estimate(_FakeConnector(), "SELECT 1", "oracle")
        assert "not supported" in result.warning.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("db_type", [
        "postgres", "mysql", "redshift",
        "databricks", "duckdb", "mssql", "trino",
    ])
    async def test_all_estimators_handle_errors(self, db_type):
        conn = _FakeConnector(error=RuntimeError("boom"))
        result = await CostEstimator.estimate(conn, "SELECT 1", db_type)
        assert result.warning is not None

    @pytest.mark.asyncio
    async def test_clickhouse_handles_errors_gracefully(self):
        """ClickHouse has dual-fallback — returns 0 rows when both paths fail."""
        conn = _FakeConnector(error=RuntimeError("boom"))
        result = await CostEstimator.estimate(conn, "SELECT 1", "clickhouse")
        # ClickHouse catches inner exceptions in try/except, so it degrades
        # gracefully to 0 estimated rows rather than propagating a warning
        assert result.estimated_rows == 0
