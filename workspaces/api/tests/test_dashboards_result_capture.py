"""Tests for dashboards result_capture pure helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from workspaces_api.dashboards.result_capture import accumulate_rows, clamp_value

# Common OIDs for testing
_OID_INT4 = 23
_OID_TEXT = 25
_OID_BOOL = 16
_OID_TIMESTAMPTZ = 1184
_OID_JSON = 114
_OID_UNKNOWN = 99999


def _make_description(names_and_oids: list[tuple[str, int]]) -> list[MagicMock]:
    """Build a fake psycopg description list."""
    cols = []
    for name, oid in names_and_oids:
        col = MagicMock()
        col.name = name
        col.type_code = oid
        cols.append(col)
    return cols


def _make_cursor(
    description: list[MagicMock],
    rows: list[tuple],
) -> AsyncMock:
    """Build a fake async psycopg cursor."""
    cursor = MagicMock()
    cursor.description = description

    async def _aiter(self: object) -> object:
        for row in rows:
            yield row

    cursor.__aiter__ = _aiter
    return cursor


class TestClampValue:
    def test_none_passes_through(self) -> None:
        v, clamped = clamp_value(None, 100)
        assert v is None
        assert clamped is False

    def test_bool_passes_through(self) -> None:
        v, clamped = clamp_value(True, 100)
        assert v is True
        assert clamped is False

    def test_int_passes_through(self) -> None:
        v, clamped = clamp_value(42, 100)
        assert v == 42
        assert clamped is False

    def test_float_passes_through(self) -> None:
        v, clamped = clamp_value(3.14, 100)
        assert v == 3.14
        assert clamped is False

    def test_short_string_passes_through(self) -> None:
        v, clamped = clamp_value("hello", 100)
        assert v == "hello"
        assert clamped is False

    def test_long_string_is_clamped(self) -> None:
        big = "x" * 200
        v, clamped = clamp_value(big, 100)
        assert clamped is True
        assert v.startswith("<truncated:")
        assert "bytes>" in v

    def test_datetime_becomes_isoformat(self) -> None:
        dt = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        v, clamped = clamp_value(dt, 1000)
        assert "2026-05-01" in v
        assert clamped is False

    def test_decimal_becomes_string(self) -> None:
        v, clamped = clamp_value(Decimal("3.14159"), 1000)
        assert v == "3.14159"
        assert clamped is False

    def test_uuid_becomes_string(self) -> None:
        uid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        v, clamped = clamp_value(uid, 1000)
        assert v == str(uid)
        assert clamped is False

    def test_bytes_becomes_string(self) -> None:
        v, clamped = clamp_value(b"rawbytes", 1000)
        assert isinstance(v, str)
        assert clamped is False


class TestAccumulateRows:
    @pytest.mark.asyncio
    async def test_columns_map_oids_to_hints(self) -> None:
        desc = _make_description([
            ("id", _OID_INT4),
            ("name", _OID_TEXT),
            ("active", _OID_BOOL),
            ("created_at", _OID_TIMESTAMPTZ),
            ("data", _OID_JSON),
            ("misc", _OID_UNKNOWN),
        ])
        cursor = _make_cursor(desc, [(1, "alice", True, "2026-05-01", "{}", "x")])
        columns, rows, truncated = await accumulate_rows(cursor, 100, 1000)

        assert columns[0] == {"name": "id", "type_hint": "int"}
        assert columns[1] == {"name": "name", "type_hint": "text"}
        assert columns[2] == {"name": "active", "type_hint": "bool"}
        assert columns[3] == {"name": "created_at", "type_hint": "timestamptz"}
        assert columns[4] == {"name": "data", "type_hint": "json"}
        assert columns[5] == {"name": "misc", "type_hint": "text"}

    @pytest.mark.asyncio
    async def test_small_input_returns_all_rows_no_truncation(self) -> None:
        desc = _make_description([("id", _OID_INT4), ("val", _OID_TEXT)])
        cursor = _make_cursor(desc, [(1, "a"), (2, "b"), (3, "c")])
        columns, rows, truncated = await accumulate_rows(cursor, 100, 1000)

        assert len(rows) == 3
        assert rows[0] == [1, "a"]
        assert truncated is False

    @pytest.mark.asyncio
    async def test_row_cap_triggers_truncation(self) -> None:
        desc = _make_description([("id", _OID_INT4)])
        data = [(i,) for i in range(15)]
        cursor = _make_cursor(desc, data)
        columns, rows, truncated = await accumulate_rows(cursor, 10, 1000)

        assert len(rows) == 10
        assert truncated is True

    @pytest.mark.asyncio
    async def test_cell_over_max_bytes_is_replaced_and_truncated(self) -> None:
        desc = _make_description([("val", _OID_TEXT)])
        big_val = "z" * 200
        cursor = _make_cursor(desc, [(big_val,)])
        columns, rows, truncated = await accumulate_rows(cursor, 100, 100)

        assert truncated is True
        cell = rows[0][0]
        assert cell.startswith("<truncated:")

    @pytest.mark.asyncio
    async def test_non_json_serializable_types_become_strings(self) -> None:
        desc = _make_description([
            ("dt", _OID_TIMESTAMPTZ),
            ("dec", _OID_INT4),
            ("uid", _OID_TEXT),
        ])
        dt = datetime(2026, 5, 1, tzinfo=timezone.utc)
        dec = Decimal("9.99")
        uid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        cursor = _make_cursor(desc, [(dt, dec, uid)])
        columns, rows, truncated = await accumulate_rows(cursor, 100, 10_000)

        assert isinstance(rows[0][0], str)
        assert isinstance(rows[0][1], str)
        assert isinstance(rows[0][2], str)
        assert truncated is False
