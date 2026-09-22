"""db.query returns typed rows; db.query_df a coerced DataFrame."""

from __future__ import annotations

from typing import Any

import pytest

from signalpilot._sdk._connection import Connection, QueryRows

_COLUMNS = [
    {"name": "client", "logical_type": "str", "nullable": False},
    {"name": "revenue", "logical_type": "decimal", "nullable": True},
    {"name": "orders", "logical_type": "integer", "nullable": False},
    {"name": "seen_at", "logical_type": "timestamp", "nullable": True},
]
# The replay cache serialises Decimal, date and datetime as strings.
_ROWS = [
    {"client": "a", "revenue": "10.50", "orders": "2", "seen_at": "2026-09-01T10:00:00"},
    {"client": "b", "revenue": None, "orders": "3", "seen_at": None},
]


class _Client:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, path: str, body: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        self.calls.append((path, body))
        return self.payload


def _connection(payload: dict[str, Any] | None = None) -> tuple[Connection, _Client]:
    client = _Client(
        payload or {"rows": _ROWS, "columns": _COLUMNS, "row_count": 2}
    )
    return Connection("warehouse", client), client  # type: ignore[arg-type]


def test_query_is_still_a_list_of_row_dicts() -> None:
    db, client = _connection()
    rows = db.query("select 1")

    assert isinstance(rows, list)
    assert isinstance(rows, QueryRows)
    assert len(rows) == 2
    assert rows[0] == _ROWS[0]
    assert rows[-1]["client"] == "b"
    assert rows[0:1] == [_ROWS[0]]
    assert [r["client"] for r in rows] == ["a", "b"]
    assert client.calls[0][1]["row_limit"] == 1000


def test_legacy_rows_key_returns_the_list_itself() -> None:
    db, _client = _connection()
    rows = db.query("select 1")
    assert rows["rows"] is rows
    assert rows.rows is rows
    assert rows["columns"] == _COLUMNS
    assert rows.get("rows") is rows
    assert rows.get("missing") is None
    with pytest.raises(KeyError):
        rows["nope"]


def test_df_coerces_by_logical_type() -> None:
    import pandas as pd

    db, _client = _connection()
    frame = db.query("select 1").df()

    assert list(frame.columns) == ["client", "revenue", "orders", "seen_at"]
    assert pd.api.types.is_numeric_dtype(frame["revenue"])
    assert pd.api.types.is_numeric_dtype(frame["orders"])
    assert pd.api.types.is_datetime64_any_dtype(frame["seen_at"])
    assert frame["revenue"].iloc[0] == pytest.approx(10.5)
    assert pd.isna(frame["revenue"].iloc[1])
    assert frame["orders"].sum() == 5
    assert (frame["revenue"] / frame["orders"]).iloc[0] == pytest.approx(5.25)


def test_query_df_returns_the_coerced_frame() -> None:
    import pandas as pd

    db, _client = _connection()
    frame = db.query_df("select 1", row_limit=5)
    assert isinstance(frame, pd.DataFrame)
    assert frame["orders"].dtype.kind in "iuf"


def test_empty_result_keeps_the_column_names() -> None:
    db, _client = _connection({"rows": [], "columns": _COLUMNS})
    rows = db.query("select 1")
    assert rows == []
    frame = rows.df()
    assert list(frame.columns) == [c["name"] for c in _COLUMNS]
    assert len(frame) == 0


def test_query_result_is_unchanged() -> None:
    db, client = _connection()
    result = db.query_result("select 1")
    assert result == client.payload
    assert isinstance(result, dict)
    assert client.calls[0][1]["row_limit"] == 100_000
