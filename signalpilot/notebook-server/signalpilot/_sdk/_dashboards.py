"""``sp.dashboard_dataset``: run one governed query and write the snapshot a
dashboard reads.

A dashboard dataset is defined by its SQL. This helper is the only writer of
the snapshot at ``artifacts/datasets/<name>.csv`` and of the sidecar at
``<scratch>/.dashboard-datasets/<name>.json`` that records which connection
and SQL produced it. The dashboard check tools compare the dashboard file
against that sidecar, so a dataset whose rows were shaped outside SQL is
reported as stale instead of rendered.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

from signalpilot._dashboard_sql import (
    is_dataset_name,
    normalized_sql_hash,
    sidecar_path,
)
from signalpilot._sdk._artifacts import artifacts_directory, scratch_directory

if TYPE_CHECKING:
    from pathlib import Path

    from signalpilot._sdk._connection import Connection

DEFAULT_ROW_LIMIT = 50_000


def _cell(value: Any) -> Any:
    """One CSV cell: numbers unquoted, None empty, dates ISO, else text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _result_columns(result: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for column in result.get("columns") or []:
        name = column.get("name") if isinstance(column, dict) else column
        if isinstance(name, str) and name not in names:
            names.append(name)
    if names:
        return names
    for row in rows:
        for key in row:
            if key not in names:
                names.append(str(key))
    return names


def write_snapshot(target: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_cell(row.get(name)) for name in columns])


def write_sidecar(
    target: Path,
    *,
    connection: str,
    sql: str,
    columns: list[str],
    row_count: int,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "connection": connection,
        "sql": sql,
        "sql_hash": normalized_sql_hash(sql),
        "columns": list(columns),
        "row_count": row_count,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")


def dashboard_dataset(
    connection: Connection,
    name: str,
    *,
    sql: str,
    row_limit: int = DEFAULT_ROW_LIMIT,
) -> Any:
    """Run ``sql`` on ``connection`` and write the dashboard snapshot.

    Returns the result as a pandas DataFrame so the caller can inspect it.

    Raises:
        ValueError: bad dataset name, empty SQL, or more rows than the limit.
        RuntimeError: the governed query failed (the gateway's message).
    """
    if not is_dataset_name(name):
        raise ValueError(
            f"Dataset name {name!r} is not valid. Use lowercase letters, "
            "digits, and '_', and start with a letter."
        )
    if not str(sql or "").strip():
        raise ValueError(f"Dataset '{name}' has no SQL.")
    if row_limit < 1:
        raise ValueError("row_limit must be at least 1.")

    result = connection.query_result(sql, row_limit)
    rows = [dict(row) for row in result.get("rows") or []]
    if result.get("completeness") == "truncated" or len(rows) > row_limit:
        raise ValueError(
            f"Dataset '{name}' has more than {row_limit} rows. Add a limit "
            "or aggregate the query."
        )
    columns = _result_columns(result, rows)

    snapshot = artifacts_directory() / "datasets" / f"{name}.csv"
    write_snapshot(snapshot, columns, rows)
    write_sidecar(
        sidecar_path(scratch_directory(), name),
        connection=connection.name,
        sql=sql,
        columns=columns,
        row_count=len(rows),
    )
    print(  # noqa: T201
        f"dashboard dataset '{name}': {len(rows)} rows, columns: "
        f"{', '.join(columns)}"
    )

    import pandas

    return pandas.DataFrame(rows, columns=columns)
