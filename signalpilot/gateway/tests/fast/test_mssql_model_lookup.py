"""SQL Server error text and cross-database model column lookup."""

from __future__ import annotations

import pymssql
import pytest

from gateway.connectors.drivers.mssql_errors import sql_server_error_text
from gateway.mcp.helpers import _get_column_names


def test_sql_server_error_drops_the_dblib_boilerplate() -> None:
    exc = pymssql.ProgrammingError(
        207,
        b"Invalid column name 'gross_margin'.DB-Lib error message 20018, severity 16:\n"
        b"General SQL Server error: Check messages from the SQL Server\n",
    )
    assert sql_server_error_text(exc) == "SQL Server error 207: Invalid column name 'gross_margin'."


def test_sql_server_error_without_a_number_keeps_the_text() -> None:
    assert sql_server_error_text(pymssql.OperationalError("connection lost")) == (
        "SQL Server error: connection lost"
    )


class _Recorder:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute(self, sql: str) -> list[dict]:
        self.sql.append(sql)
        return [{"column_name": "gm"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("db_type", "name", "fragments"),
    [
        ("mssql", "Analytics.core.core_pl_monthly", ["FROM Analytics.information_schema.columns", "table_schema = 'core'"]),
        ("mssql", "core_pl_monthly", ["FROM information_schema.columns", "table_schema = 'dbo'"]),
        ("snowflake", "DB.S.T", ["FROM DB.information_schema.columns"]),
        ("postgres", "db.s.t", ["FROM information_schema.columns", "table_catalog = 'db'"]),
        ("postgres", "t", ["table_schema = 'public'"]),
    ],
)
async def test_column_lookup_scopes_to_the_model_database(
    db_type: str, name: str, fragments: list[str]
) -> None:
    connector = _Recorder()
    assert await _get_column_names(connector, db_type, name) == ["gm"]
    for fragment in fragments:
        assert fragment in connector.sql[0]
