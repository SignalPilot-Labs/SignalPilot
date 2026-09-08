"""The dashboard dataset snapshot convention, shared by the sandbox SDK,
the published-dashboard loader (the two writers), and the dashboard check
tools (the readers).

A dashboard dataset is defined by its SQL. The snapshot is the cached
result of that SQL at ``artifacts/datasets/<name>.csv`` in the chat scratch
directory. A sidecar at ``<scratch>/.dashboard-datasets/<name>.json``
records which connection and SQL produced the snapshot, so a check tool can
tell when the dashboard file and the snapshot no longer agree. The dot
directory keeps the sidecar out of the artifact sweep.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

DATASET_NAME_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
SNAPSHOT_DIRECTORY = "artifacts/datasets"
SIDECAR_DIRECTORY = ".dashboard-datasets"

_DATASET_NAME_RE = re.compile(DATASET_NAME_PATTERN)
_WHITESPACE_RE = re.compile(r"\s+")


def is_dataset_name(name: object) -> bool:
    return isinstance(name, str) and _DATASET_NAME_RE.match(name) is not None


def normalized_sql(sql: str) -> str:
    """Strip surrounding whitespace and collapse internal runs to one space."""
    return _WHITESPACE_RE.sub(" ", str(sql or "").strip())


def normalized_sql_hash(sql: str) -> str:
    """SHA-256 hex digest of the normalized SQL text."""
    return hashlib.sha256(normalized_sql(sql).encode("utf-8")).hexdigest()


def snapshot_path(name: str) -> str:
    """Scratch-relative POSIX path of a dataset snapshot."""
    return f"{SNAPSHOT_DIRECTORY}/{name}.csv"


def sidecar_path(scratch_directory: Path, name: str) -> Path:
    """Absolute path of the sidecar that records a snapshot's origin."""
    return scratch_directory / SIDECAR_DIRECTORY / f"{name}.json"


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


def row_columns(rows: list[dict[str, Any]]) -> list[str]:
    """Column names in first-seen order across the rows."""
    names: list[str] = []
    for row in rows:
        for key in row:
            if key not in names:
                names.append(str(key))
    return names


def write_snapshot(
    target: Path, columns: list[str], rows: list[dict[str, Any]]
) -> None:
    """Write the CSV snapshot: a header row, then one row per record."""
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
    origin: dict[str, Any] | None = None,
) -> None:
    """Record which connection and SQL produced a snapshot.

    ``origin`` names the published dashboard version the rows came from
    when the snapshot was loaded from the gateway instead of a query.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "connection": connection,
        "sql": sql,
        "sql_hash": normalized_sql_hash(sql),
        "columns": list(columns),
        "row_count": row_count,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    if origin:
        record["origin"] = dict(origin)
    target.write_text(json.dumps(record, indent=2), encoding="utf-8")
