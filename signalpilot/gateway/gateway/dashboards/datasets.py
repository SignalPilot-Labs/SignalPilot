"""Dataset bytes: parsing, writing, and manifest reference resolution.

Parsing mirrors the notebook-server loader: CSV and TSV have a header row,
fully numeric cells become ``int`` or ``float``, empty cells become ``None``.
JSON is an array of flat objects.

Reference resolution mirrors ``web/lib/chat-file-refs.ts``: an absolute
sandbox path keeps the tail after the run root, leading ``./`` and ``/`` are
stripped, and the result must start with ``artifacts/``.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Any, Protocol

Row = dict[str, Any]

ARTIFACTS_PREFIX = "artifacts/"
MAX_DATASET_BYTES = 50 * 1024 * 1024

_RUN_ROOT_RE = re.compile(r"signalpilot-chat-runs/[^/]+/(.+)$")
_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)

_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
}


# ── Parsing ──────────────────────────────────────────────────────────────────


def coerce_cell(value: str | None) -> Any:
    """Coerce one delimited cell: empty -> None, fully numeric -> int or float."""
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
    """Parse by extension (csv, tsv, json). Raises ValueError on bad input."""
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".csv":
        return parse_delimited(text, delimiter=",")
    if suffix == ".tsv":
        return parse_delimited(text, delimiter="\t")
    if suffix == ".json":
        return parse_json_rows(text)
    raise ValueError(f"Unsupported dataset file type: {filename}")


def parse_dataset_bytes(data: bytes, filename: str) -> list[Row]:
    if len(data) > MAX_DATASET_BYTES:
        raise ValueError(f"Dataset file is larger than 50 MB: {filename}")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Dataset file is not UTF-8 text: {filename}") from exc
    try:
        return parse_dataset_text(text, filename)
    except csv.Error as exc:
        raise ValueError(f"Dataset file could not be parsed: {filename} ({exc})") from exc


def inline_rows(definition: dict[str, Any]) -> list[Row] | None:
    """Rows of an inline dataset definition, or None when it is file-backed."""
    rows = definition.get("rows")
    if rows is None:
        return None
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, dict)]


# ── Writing ──────────────────────────────────────────────────────────────────


def csv_cell(value: Any) -> str:
    """Format one query result value for CSV: ISO dates, empty for null."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return repr(value) if not value.is_integer() else str(int(value))
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict | list):
        return json.dumps(value, default=str, ensure_ascii=False)
    return str(value)


def rows_to_csv(columns: list[str], rows: list[Row]) -> bytes:
    """Serialize query rows to UTF-8 CSV. Header is the column list."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([csv_cell(row.get(column)) for column in columns])
    return buffer.getvalue().encode("utf-8")


def rows_to_json(rows: list[Row]) -> bytes:
    return json.dumps(rows, default=str, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def result_columns(columns: list[dict[str, Any]] | None, rows: list[Row]) -> list[str]:
    """Column order of a query result: metadata first, else the first row's keys."""
    names = [str(item.get("name")) for item in columns or [] if isinstance(item, dict) and item.get("name")]
    if names:
        return names
    return [str(key) for key in rows[0]] if rows else []


# ── Names and content types ─────────────────────────────────────────────────


def dataset_extension(filename: str) -> str:
    """The stored extension for a dataset file: csv, tsv, or json."""
    suffix = PurePosixPath(filename).suffix.lower().lstrip(".")
    return suffix if suffix in {"csv", "tsv", "json"} else "csv"


def content_type_for(filename: str) -> str:
    return _CONTENT_TYPES.get(PurePosixPath(filename).suffix.lower(), "application/octet-stream")


# ── Manifest reference resolution ────────────────────────────────────────────


class ManifestRow(Protocol):
    """The conversation file row fields the resolver and publisher read."""

    path: str
    filename: str
    status: str
    object_key: str
    origin_run_id: str | None
    updated_at: Any


def normalize_file_ref(value: str | None) -> str | None:
    """Port of ``normalizeFileRef``: a manifest-shaped relative path or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if _SCHEME_RE.match(text) or text.startswith("//"):
        return None
    text = re.split(r"[?#]", text, maxsplit=1)[0]
    text = text.replace("\\", "/")
    if text.startswith("/"):
        run_match = _RUN_ROOT_RE.search(text)
        artifacts_index = text.rfind("/artifacts/")
        if run_match:
            text = run_match.group(1)
        elif artifacts_index >= 0:
            text = text[artifacts_index + 1 :]
        else:
            text = text.rsplit("/", 1)[-1]
    text = re.sub(r"^(?:\.\.?/|/)+", "", text)
    text = text.replace("/./", "/")
    return text or None


def is_artifact_ref(norm: str | None) -> bool:
    """True when a normalized reference lives under ``artifacts/`` and has no ``..``."""
    if not norm or not norm.startswith(ARTIFACTS_PREFIX) or norm == ARTIFACTS_PREFIX:
        return False
    return all(segment not in {"", ".", ".."} for segment in norm.split("/"))


def resolve_file_ref(
    norm: str | None,
    rows: list[ManifestRow],
    *,
    run_id: str | None = None,
) -> ManifestRow | None:
    """Port of ``resolveFileRef``: one active manifest row or None."""
    if not norm:
        return None
    active = [row for row in rows if row.status == "active"]
    for row in active:
        if row.path == norm:
            return row
    for row in active:
        if row.path == f"artifacts/{norm}":
            return row
    suffix_matches = [row for row in active if row.path.endswith(f"/{norm}")]
    if len(suffix_matches) == 1:
        return suffix_matches[0]
    basename = norm.rsplit("/", 1)[-1]
    by_name = [row for row in active if row.filename == basename]
    if not by_name:
        return None
    by_name.sort(
        key=lambda row: (
            1 if run_id and row.origin_run_id == run_id else 0,
            str(row.updated_at or ""),
        ),
        reverse=True,
    )
    return by_name[0]


@dataclass(frozen=True)
class ResolvedDataset:
    name: str
    path: str
    row: ManifestRow | None
    error: str | None = None


def resolve_dataset_refs(
    refs: dict[str, str],
    rows: list[ManifestRow],
    *,
    run_id: str | None = None,
) -> list[ResolvedDataset]:
    """Resolve every ``datasets.<name>.file`` against the conversation manifest."""
    resolved: list[ResolvedDataset] = []
    for name, ref in refs.items():
        norm = normalize_file_ref(ref)
        if not is_artifact_ref(norm):
            resolved.append(ResolvedDataset(name, ref, None, f"Dataset '{name}' path must be under artifacts/: {ref}"))
            continue
        row = resolve_file_ref(norm, rows, run_id=run_id)
        if row is None:
            resolved.append(ResolvedDataset(name, ref, None, f"Dataset '{name}' file is not in the conversation: {ref}"))
            continue
        resolved.append(ResolvedDataset(name, ref, row))
    return resolved
