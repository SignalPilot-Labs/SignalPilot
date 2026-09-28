"""Profiling cost is rows x columns, not rows.

`_profile_exact` emits one `COUNT(DISTINCT col)` per column, and each is its own
aggregation. A rows-only threshold therefore misses wide tables entirely: on the
Dumpsters estate `core_transaction_line` is 267 columns x 316,874 rows = 84.6M
cells and sat under a 2,000,000-row gate, so `map_columns` ran unsampled for
9m44s until the MCP transport dropped the call and the whole result was lost.

These tests pin the three properties that fix introduced: gate on cells, chunk
the aggregates, and stop at a deadline with partial results.
"""

from __future__ import annotations

import time

import pytest

from gateway.mcp.tools import model_map


class _Schema:
    def __init__(self, dialect: str, rows: int) -> None:
        self.dialect = dialect
        self._rows = rows

    def resolve(self, table_name: str) -> str:
        return f"dbo.{table_name}"

    def row_count(self, _table_name: str) -> int:
        return self._rows


class _Connector:
    """Records every statement and answers with plausible aggregate rows."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def quote_table(self, key: str) -> str:
        return f"[{key}]"

    def quote_identifier(self, name: str) -> str:
        return f"[{name}]"

    async def execute(self, sql: str, *_args):
        self.statements.append(sql)
        row: dict[str, object] = {"total": 100}
        for i in range(sql.count("AS nn")):
            row[f"nn{i}"] = 100
            row[f"d{i}"] = 7
        return [row]


def _columns(n: int) -> list[tuple[str, str]]:
    return [(f"col_{i}", "int") for i in range(n)]


@pytest.mark.asyncio
async def test_wide_table_under_the_row_gate_is_still_sampled() -> None:
    # The real shape that broke: far below _BIG rows, far above _BIG_CELLS.
    rows, cols = 316_874, 267
    assert rows < model_map._BIG, "fixture must sit under the old rows-only gate"
    assert rows * cols > model_map._BIG_CELLS

    connector = _Connector()
    profile = await model_map._profile_columns(
        connector, _Schema("mssql", rows), "core_transaction_line", _columns(cols)
    )

    assert profile, "a sampled profile should still return column stats"
    assert all("TOP" in s for s in connector.statements), (
        "every statement must read a bounded sample, not the whole table"
    )
    assert all(stats["estimated"] for stats in profile.values()), (
        "sampled distinct counts are estimates and must be labelled as such"
    )


@pytest.mark.asyncio
async def test_narrow_table_under_the_cell_gate_stays_exact() -> None:
    connector = _Connector()
    profile = await model_map._profile_columns(
        connector, _Schema("mssql", 50_000), "small_mart", _columns(8)
    )
    assert profile
    assert not any("TOP" in s for s in connector.statements), (
        "a cheap table must not be sampled; exact counts are the contract"
    )
    assert not any("estimated" in stats for stats in profile.values())


@pytest.mark.asyncio
async def test_aggregates_are_chunked_per_statement() -> None:
    connector = _Connector()
    cols = model_map._MAX_DISTINCTS_PER_QUERY * 3 + 5
    await model_map._profile_columns(
        connector, _Schema("mssql", 1_000), "wide_but_small", _columns(cols)
    )
    assert len(connector.statements) >= 4, "columns must be split across statements"
    for sql in connector.statements:
        assert sql.count("COUNT(DISTINCT") <= model_map._MAX_DISTINCTS_PER_QUERY


@pytest.mark.asyncio
async def test_expired_deadline_returns_partial_instead_of_running_on() -> None:
    connector = _Connector()
    columns = _columns(model_map._MAX_DISTINCTS_PER_QUERY * 4)
    profile = await model_map._profile_exact(
        connector,
        _Schema("mssql", 1_000),
        "dbo.t",
        columns,
        None,
        deadline=time.monotonic() - 1.0,
    )
    assert profile == {}
    assert connector.statements == [], "an expired budget must issue no statements"


def test_budget_is_shorter_than_the_transport_patience() -> None:
    # The failure mode was outliving the MCP transport, so the budget must leave
    # room for the rest of the call to return.
    assert 0 < model_map._PROFILE_BUDGET_SECONDS <= 120
