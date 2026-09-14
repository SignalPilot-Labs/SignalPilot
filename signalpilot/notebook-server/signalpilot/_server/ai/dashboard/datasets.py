"""Load dashboard datasets from the chat scratch directory.

A dataset is ``{"connection": ..., "sql": ...}`` or ``{"rows": [...]}``.

A SQL dataset is defined by its SQL; its rows are the snapshot at
``artifacts/datasets/<name>.csv`` written by ``sp.dashboard_dataset``. The
sidecar at ``<scratch>/.dashboard-datasets/<name>.json`` records the
connection, the SQL hash, and the columns that produced the snapshot. When
the dashboard file and the sidecar disagree the dataset is ``snapshot_stale``;
when the snapshot file is absent it is ``snapshot_missing``.

CSV has a header row; cells that are fully numeric are coerced to ``int`` or
``float`` and empty cells become ``None``. Static ``rows`` are used inline.

Path safety: a relative path must start with ``artifacts/``, must not contain
``..`` segments, and must resolve inside the scratch directory.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from signalpilot._dashboard_sql import (
    normalized_sql_hash,
    sidecar_path,
    snapshot_path,
)

Row = dict[str, Any]

MAX_FILE_BYTES = 50 * 1024 * 1024
_ARTIFACTS_PREFIX = "artifacts/"

SNAPSHOT_MISSING = "snapshot_missing"
SNAPSHOT_STALE = "snapshot_stale"
DATASET_UNREADABLE = "dataset_unreadable"


@dataclass
class LoadedDataset:
    """One dataset after loading.

    ``error`` is set when the dataset cannot be used; ``code`` is then the
    issue code (``snapshot_missing``, ``snapshot_stale``, or
    ``dataset_unreadable``). ``resolved_file`` is the snapshot path for a
    SQL dataset and ``None`` for static rows.
    """

    rows: list[Row] = field(default_factory=list)
    resolved_file: str | None = None
    error: str | None = None
    code: str | None = None


def resolve_scratch_path(scratch_directory: Path, relative: str) -> Path:
    """Resolve a scratch-relative artifact path safely.

    Raises:
        ValueError: when the path is outside ``artifacts/`` or escapes the
            scratch directory.
    """
    text = str(relative or "").strip().replace("\\", "/")
    if not text.startswith(_ARTIFACTS_PREFIX) or text == _ARTIFACTS_PREFIX:
        raise ValueError(f"Path must start with '{_ARTIFACTS_PREFIX}': {text}")
    for segment in text.split("/"):
        if not segment or segment in {".", ".."}:
            raise ValueError(f"Path must not contain '{segment}': {text}")
    root = scratch_directory.resolve()
    candidate = (root / PurePosixPath(text)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Path escapes the scratch directory: {text}"
        ) from exc
    return candidate


def coerce_cell(value: str | None) -> Any:
    """Coerce one CSV cell: empty -> None, fully numeric -> int or float."""
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        return value
    if math.isnan(number) or math.isinf(number):
        return value
    return number


def parse_csv(text: str) -> tuple[list[str], list[Row]]:
    """Parse CSV text with a header row into (header, rows)."""
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return [], []
    names = [name.strip() for name in header]
    rows: list[Row] = []
    for record in reader:
        if not record or all(cell.strip() == "" for cell in record):
            continue
        row: Row = {}
        for index, name in enumerate(names):
            cell = record[index] if index < len(record) else None
            row[name] = coerce_cell(cell)
        rows.append(row)
    return names, rows


def _stale(name: str, snapshot: str, reason: str) -> LoadedDataset:
    return LoadedDataset(
        resolved_file=snapshot,
        code=SNAPSHOT_STALE,
        error=(
            f"Dataset '{name}' snapshot is stale: {reason}. Call "
            f"sp.dashboard_dataset('{name}', connection=..., sql=...) again "
            "with the SQL from the dashboard file."
        ),
    )


def _read_sidecar(scratch_directory: Path, name: str) -> dict[str, Any] | None:
    target = sidecar_path(scratch_directory, name)
    if not target.is_file():
        return None
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _load_sql_dataset(
    scratch_directory: Path, name: str, definition: dict[str, Any]
) -> LoadedDataset:
    snapshot = snapshot_path(name)
    connection = str(definition.get("connection") or "")
    sql = str(definition.get("sql") or "")
    try:
        target = resolve_scratch_path(scratch_directory, snapshot)
    except ValueError as exc:
        return LoadedDataset(
            error=str(exc), resolved_file=snapshot, code=DATASET_UNREADABLE
        )
    if not target.is_file():
        return LoadedDataset(
            resolved_file=snapshot,
            code=SNAPSHOT_MISSING,
            error=(
                f"Dataset '{name}' has no snapshot. Call "
                f"sp.dashboard_dataset('{name}', connection=..., sql=...) "
                "in the notebook."
            ),
        )
    try:
        if target.stat().st_size > MAX_FILE_BYTES:
            return LoadedDataset(
                error=f"Dataset snapshot is larger than 50 MB: {snapshot}",
                resolved_file=snapshot,
                code=DATASET_UNREADABLE,
            )
        header, rows = parse_csv(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, csv.Error) as exc:
        return LoadedDataset(
            error=f"Dataset snapshot could not be parsed: {snapshot} ({exc})",
            resolved_file=snapshot,
            code=DATASET_UNREADABLE,
        )

    sidecar = _read_sidecar(scratch_directory, name)
    if sidecar is None:
        return _stale(
            name,
            snapshot,
            f"the snapshot {snapshot} has no record of the SQL that "
            "produced it",
        )
    recorded_connection = str(sidecar.get("connection") or "")
    if recorded_connection != connection:
        return _stale(
            name,
            snapshot,
            f"the connection in the dashboard file ('{connection}') is not "
            f"the connection that produced the snapshot "
            f"('{recorded_connection}')",
        )
    if str(sidecar.get("sql_hash") or "") != normalized_sql_hash(sql):
        return _stale(
            name,
            snapshot,
            "the SQL in the dashboard file is not the SQL that produced the "
            "snapshot",
        )
    recorded_columns = [str(item) for item in sidecar.get("columns") or []]
    if header != recorded_columns:
        return _stale(
            name,
            snapshot,
            f"the snapshot columns ({', '.join(header) or 'none'}) are not "
            f"the recorded columns ({', '.join(recorded_columns) or 'none'})",
        )
    return LoadedDataset(rows=rows, resolved_file=snapshot)


def load_dataset(
    scratch_directory: Path, name: str, definition: Any
) -> LoadedDataset:
    """Load one dataset definition. Never raises; sets ``error`` instead."""
    if not isinstance(definition, dict):
        return LoadedDataset(
            error="Dataset definition is not an object", code=DATASET_UNREADABLE
        )
    inline = definition.get("rows")
    if inline is not None:
        if not isinstance(inline, list):
            return LoadedDataset(
                error="Dataset rows must be an array", code=DATASET_UNREADABLE
            )
        rows = [dict(item) for item in inline if isinstance(item, dict)]
        return LoadedDataset(rows=rows)
    if definition.get("connection") and definition.get("sql"):
        return _load_sql_dataset(scratch_directory, name, definition)
    return LoadedDataset(
        error="Dataset has neither connection and sql nor rows",
        code=DATASET_UNREADABLE,
    )


def load_datasets(
    scratch_directory: Path,
    spec: dict[str, Any],
    names: set[str] | None = None,
) -> dict[str, LoadedDataset]:
    """Load the named datasets of a spec (all of them when ``names`` is None)."""
    definitions = spec.get("datasets")
    definitions = definitions if isinstance(definitions, dict) else {}
    loaded: dict[str, LoadedDataset] = {}
    for name, definition in definitions.items():
        if names is not None and name not in names:
            continue
        loaded[name] = load_dataset(scratch_directory, str(name), definition)
    return loaded
