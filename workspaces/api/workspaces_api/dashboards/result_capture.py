"""Pure helpers for capturing and bounding psycopg query results.

Functions:
  clamp_value(v, max_bytes) -> tuple[Any, bool]
      Converts a cell value to a JSON-serializable type, clamping oversize
      strings to a placeholder.

  accumulate_rows(cursor, max_rows, max_cell_bytes) -> tuple[columns, rows, truncated]
      Reads all rows from an async psycopg cursor up to max_rows, clamping
      each cell.  Marks truncated=True when either the row cap or cell cap fires.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# Mapping of PostgreSQL OIDs to human-readable type hints.
# Unknown OIDs default to "text".
_OID_HINTS: dict[int, str] = {
    # integer types
    20: "int",   # int8 / bigint
    21: "int",   # int2 / smallint
    23: "int",   # int4 / integer
    26: "int",   # oid
    # text types
    25: "text",  # text
    1043: "text",  # varchar
    18: "text",  # char
    19: "text",  # name
    # boolean
    16: "bool",
    # floating point
    700: "float",   # float4
    701: "float",   # float8
    # numeric / decimal
    1700: "numeric",
    # timestamps
    1114: "timestamptz",  # timestamp without tz (displayed as timestamptz)
    1184: "timestamptz",  # timestamptz
    1082: "timestamptz",  # date
    # json/jsonb
    114: "json",   # json
    3802: "json",  # jsonb
}


def _oid_to_hint(type_code: int) -> str:
    return _OID_HINTS.get(type_code, "text")


def clamp_value(v: Any, max_bytes: int) -> tuple[Any, bool]:
    """Convert v to a JSON-serializable form; clamp if string exceeds max_bytes.

    Returns (serializable_value, was_clamped).
    None, bool, int, float, str pass through directly (no conversion needed).
    datetime, date, Decimal, UUID, bytes are stringified.
    All other types are stringified via str().
    If the resulting string's UTF-8 encoding exceeds max_bytes, return a
    placeholder string and was_clamped=True.
    """
    if v is None or isinstance(v, bool):
        return v, False
    if isinstance(v, (int, float)):
        return v, False
    if isinstance(v, str):
        serializable: Any = v
    elif isinstance(v, (datetime, date)):
        serializable = v.isoformat()
    elif isinstance(v, Decimal):
        serializable = str(v)
    elif isinstance(v, uuid.UUID):
        serializable = str(v)
    elif isinstance(v, (bytes, bytearray, memoryview)):
        serializable = str(v)
    else:
        serializable = str(v)

    encoded = serializable.encode("utf-8")
    if len(encoded) > max_bytes:
        return f"<truncated:{len(encoded)} bytes>", True
    return serializable, False


async def accumulate_rows(
    cursor: Any,
    max_rows: int,
    max_cell_bytes: int,
) -> tuple[list[dict[str, str]], list[list[Any]], bool]:
    """Accumulate rows from an async psycopg cursor with caps.

    Args:
        cursor: an open psycopg async cursor (post execute()).
        max_rows: maximum number of rows to accumulate.
        max_cell_bytes: maximum UTF-8 byte length per cell string.

    Returns:
        (columns, rows, truncated) where:
          columns: list of {"name": str, "type_hint": str}
          rows: list of row lists (JSON-serializable values)
          truncated: True if row cap or cell cap was hit
    """
    description = cursor.description or []
    columns = [
        {"name": col.name, "type_hint": _oid_to_hint(col.type_code)}
        for col in description
    ]

    rows: list[list[Any]] = []
    truncated = False

    async for raw_row in cursor:
        if len(rows) >= max_rows:
            # We've fetched one extra row — row cap hit
            truncated = True
            break

        row: list[Any] = []
        for cell in raw_row:
            clamped, was_clamped = clamp_value(cell, max_cell_bytes)
            row.append(clamped)
            if was_clamped:
                truncated = True
        rows.append(row)

    return columns, rows, truncated


__all__ = ["clamp_value", "accumulate_rows"]
