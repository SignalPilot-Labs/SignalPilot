"""Load dashboard datasets from the chat scratch directory.

A dataset is ``{"file": "artifacts/x.csv|tsv|json"}`` or ``{"rows": [...]}``.
CSV and TSV have a header row; cells that are fully numeric are coerced to
``int`` or ``float`` and empty cells become ``None``. JSON is an array of flat
objects.

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

Row = dict[str, Any]

MAX_FILE_BYTES = 50 * 1024 * 1024
_ARTIFACTS_PREFIX = "artifacts/"


@dataclass
class LoadedDataset:
    """One dataset after loading. ``error`` is set when it is unreadable."""

    rows: list[Row] = field(default_factory=list)
    resolved_file: str | None = None
    error: str | None = None


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


def parse_delimited(text: str, *, delimiter: str) -> list[Row]:
    """Parse CSV or TSV text with a header row into flat rows."""
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        return []
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
    return rows


def parse_json_rows(text: str) -> list[Row]:
    """Parse a JSON array of flat objects.

    Raises:
        ValueError: when the document is not an array of objects.
    """
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("JSON dataset must be an array of objects")
    rows: list[Row] = []
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"JSON dataset item {index} is not an object")
        rows.append(dict(item))
    return rows


def parse_dataset_text(text: str, filename: str) -> list[Row]:
    """Parse dataset text by file extension (csv, tsv, json)."""
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".csv":
        return parse_delimited(text, delimiter=",")
    if suffix == ".tsv":
        return parse_delimited(text, delimiter="\t")
    if suffix == ".json":
        return parse_json_rows(text)
    raise ValueError(f"Unsupported dataset file type: {filename}")


def load_dataset(scratch_directory: Path, definition: Any) -> LoadedDataset:
    """Load one dataset definition. Never raises; sets ``error`` instead."""
    if not isinstance(definition, dict):
        return LoadedDataset(error="Dataset definition is not an object")
    inline = definition.get("rows")
    if inline is not None:
        if not isinstance(inline, list):
            return LoadedDataset(error="Dataset rows must be an array")
        rows = [dict(item) for item in inline if isinstance(item, dict)]
        return LoadedDataset(rows=rows)
    file_ref = definition.get("file")
    if not isinstance(file_ref, str) or not file_ref:
        return LoadedDataset(error="Dataset has neither file nor rows")
    try:
        target = resolve_scratch_path(scratch_directory, file_ref)
    except ValueError as exc:
        return LoadedDataset(error=str(exc), resolved_file=file_ref)
    if not target.is_file():
        return LoadedDataset(
            error=f"Dataset file not found: {file_ref}",
            resolved_file=file_ref,
        )
    try:
        if target.stat().st_size > MAX_FILE_BYTES:
            return LoadedDataset(
                error=f"Dataset file is larger than 50 MB: {file_ref}",
                resolved_file=file_ref,
            )
        text = target.read_text(encoding="utf-8-sig")
        rows = parse_dataset_text(text, file_ref)
    except (OSError, ValueError, csv.Error) as exc:
        return LoadedDataset(
            error=f"Dataset file could not be parsed: {file_ref} ({exc})",
            resolved_file=file_ref,
        )
    return LoadedDataset(rows=rows, resolved_file=file_ref)


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
        loaded[name] = load_dataset(scratch_directory, definition)
    return loaded
