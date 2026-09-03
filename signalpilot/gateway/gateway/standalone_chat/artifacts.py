"""Table snapshot helpers shared by the saved-reports library."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
_FORMULA_PREFIXES = ("=", "+", "-", "@")
MAX_TABLE_ROWS = 200


def safe_filename(filename: str, *, fallback: str) -> str:
    normalized = _SAFE_FILENAME_RE.sub("_", filename).strip(" .")
    return (normalized or fallback)[:255]


def protect_csv_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def normalize_table_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bound only the UI preview; full governed downloads live in object storage."""
    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        rows = []
    return {
        **snapshot,
        "rows": rows[:MAX_TABLE_ROWS],
        "display_limited": len(rows) > MAX_TABLE_ROWS,
        "saved_row_count": snapshot.get("saved_row_count", len(rows)),
        "truncated": bool(snapshot.get("truncated")),
    }


def table_to_csv(snapshot: dict[str, Any]) -> bytes:
    columns = snapshot.get("columns") or []
    names = [str(column.get("name") if isinstance(column, dict) else column) for column in columns]
    rows = snapshot.get("rows") or []
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(names)
    for row in rows:
        if isinstance(row, dict):
            writer.writerow([protect_csv_cell(row.get(name, "")) for name in names])
        elif isinstance(row, list):
            writer.writerow([protect_csv_cell(value) for value in row[: len(names)]])
    if snapshot.get("truncated"):
        writer.writerow([])
        writer.writerow(["Data truncated by the governed query row limit."])
    return output.getvalue().encode("utf-8-sig")
