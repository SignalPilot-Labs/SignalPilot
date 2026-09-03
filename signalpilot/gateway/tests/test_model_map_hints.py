"""Driving-table and staging hints: aliased scans, budget, catalog-first."""

from __future__ import annotations

import pytest

from gateway.mcp.tools import model_map_hints as hints
from gateway.mcp.tools.model_map import _Schema


def _raw(tables: dict[str, dict]) -> dict:
    """Build a get_schema-shaped dict. tables: name -> {cols, rows, distinct}."""
    raw = {}
    for name, spec in tables.items():
        cols = []
        for col in spec["cols"]:
            entry = {"name": col, "type": "int"}
            distinct = spec.get("distinct", {}).get(col)
            if distinct is not None:
                entry["stats"] = {"distinct_count": distinct}
            cols.append(entry)
        raw[f"dbo.{name}"] = {"name": name, "columns": cols, "row_count": spec.get("rows", 0)}
    return raw


class FakeConnector:
    """Returns dict rows like the SQL Server driver and records every SQL."""

    def __init__(self, answers: dict[str, list[int]]):
        self.answers = answers
        self.queries: list[str] = []

    def _quote_identifier(self, name: str) -> str:
        return f"[{name}]"

    def _quote_table(self, name: str) -> str:
        return f"[{name}]"

    async def execute(self, sql: str):
        self.queries.append(sql)
        table = sql.rsplit("FROM ", 1)[1].strip("[]").split(".")[-1]
        if table not in self.answers:
            raise RuntimeError("Specified as_dict=True and there are columns with no names")
        values = self.answers[table]
        return [{f"d{i}": v for i, v in enumerate(values)}]


@pytest.mark.asyncio
async def test_scans_are_aliased_and_read_by_position():
    schema = _Schema(
        _raw(
            {
                "customers": {"cols": ["id", "name"], "rows": 100},
                "orders": {"cols": ["id", "customer_id"], "rows": 500},
            }
        ),
        "mssql",
    )
    connector = FakeConnector({"customers": [100], "orders": [80]})
    out = await hints._driving_table_gaps(connector, schema)
    assert out == [
        "  customers.id ↔ orders.customer_id: ~20 of 100 parent keys are not referenced by "
        "orders (some parents have no children). Drive FROM customers LEFT JOIN orders."
    ]
    assert all(" AS d0" in q for q in connector.queries)
    assert len(connector.queries) == 2


@pytest.mark.asyncio
async def test_catalog_stats_avoid_scans():
    schema = _Schema(
        _raw(
            {
                "customers": {"cols": ["id"], "rows": 100, "distinct": {"id": 100}},
                "orders": {"cols": ["id", "customer_id"], "rows": 500, "distinct": {"customer_id": 90}},
            }
        ),
        "postgresql",
    )
    connector = FakeConnector({})
    out = await hints._driving_table_gaps(connector, schema)
    assert len(out) == 1 and "~10 of 100" in out[0]
    assert connector.queries == []


@pytest.mark.asyncio
async def test_budget_stops_scanning_and_reports_partial():
    tables = {"customers": {"cols": ["id"], "rows": 100}}
    for index in range(6):
        tables[f"customer_events_{index}"] = {"cols": ["id", "customer_id"], "rows": 50}
    schema = _Schema(_raw(tables), "mssql")
    connector = FakeConnector({name: [100] for name in tables})
    budget = hints.ScanBudget(seconds=0, max_scans=3)
    out = await hints._driving_table_gaps(connector, schema, budget=budget)
    assert budget.exhausted
    assert len(connector.queries) == 3
    assert out[-1].startswith("  (driving-table scan stopped after 3 table scans")


@pytest.mark.asyncio
async def test_unscannable_tables_cost_nothing():
    """Views (row_count 0) and huge row-store tables are skipped without a query."""
    schema = _Schema(
        _raw(
            {
                "customers": {"cols": ["id"], "rows": 0},
                "orders": {"cols": ["id", "customer_id"], "rows": 5_000_000},
            }
        ),
        "mssql",
    )
    connector = FakeConnector({})
    out = await hints._driving_table_gaps(connector, schema)
    assert out == []
    assert connector.queries == []


@pytest.mark.asyncio
async def test_failed_scan_is_swallowed():
    schema = _Schema(
        _raw(
            {
                "customers": {"cols": ["id"], "rows": 100},
                "orders": {"cols": ["id", "customer_id"], "rows": 500},
            }
        ),
        "mssql",
    )
    connector = FakeConnector({})
    assert await hints._driving_table_gaps(connector, schema) == []


@pytest.mark.asyncio
async def test_staging_gap_hint():
    schema = _Schema(
        _raw(
            {
                "orders": {"cols": ["id"], "rows": 5000},
                "stg_orders": {"cols": ["id"], "rows": 4800},
            }
        ),
        "duckdb",
    )
    out = await hints._staging_gaps(schema)
    assert out == ["  stg_orders: ~4800 rows (raw orders: ~5000 — staging filters ~200). Use ref('stg_orders') not source()."]


def test_scan_budget_env_defaults(monkeypatch):
    monkeypatch.setenv("SP_DB_HINTS_SCAN_BUDGET_SECONDS", "7")
    monkeypatch.setenv("SP_DB_HINTS_MAX_SCANS", "not-a-number")
    budget = hints.ScanBudget()
    assert budget.seconds == 7.0
    assert budget.max_scans == 40
