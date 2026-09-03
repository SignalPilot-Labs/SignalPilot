"""Bound-parameter coverage for the production sandboxed DuckDB path."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import date, datetime
from decimal import Decimal

import duckdb

from gateway.connectors.drivers.sandboxed_duckdb import _build_query_code


def test_sandboxed_duckdb_executes_typed_parameters_without_sql_interpolation(tmp_path) -> None:
    database_path = tmp_path / "bindings.duckdb"
    duckdb.connect(str(database_path)).close()
    payload = "North' OR 1=1 -- ?"
    sql = "SELECT ? AS text_value, ? AS date_value, ? AS timestamp_value, ? AS amount"
    code = _build_query_code(
        sql,
        [
            payload,
            date(2026, 7, 1),
            datetime(2026, 7, 1, 12, 30),
            Decimal("42.75"),
        ],
        db_path=str(database_path),
    )

    assert payload not in code
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exec(code, {})

    result = json.loads(output.getvalue())
    assert result["rows"] == [
        {
            "text_value": payload,
            "date_value": "2026-07-01",
            "timestamp_value": "2026-07-01T12:30:00",
            "amount": 42.75,
        }
    ]
