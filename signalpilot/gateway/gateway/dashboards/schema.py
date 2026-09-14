"""Dashboard spec schema: the bundled copy, validation, and dataset shapes.

``dashboard.schema.json`` next to this module is a byte-identical copy of
``signalpilot-plugin/skills/dashboard/dashboard.schema.json``. A test asserts
the identity; update both files together.

A dataset is either SQL (``connection`` + ``sql``; its rows are the query
result, cached as a snapshot at ``artifacts/datasets/<name>.csv`` in the
chat) or static (``rows`` inline in the spec; never refreshed).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("dashboard.schema.json")
SNAPSHOT_DIR = "artifacts/datasets"

_MAX_ERRORS = 20


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


def _error_path(error: Any) -> str:
    parts = [str(part) for part in error.absolute_path]
    return "/".join(parts) if parts else "(root)"


def validate_spec(spec: Any) -> list[str]:
    """Return a list of human-readable errors; empty when the spec is valid."""
    if not isinstance(spec, dict):
        return ["Dashboard spec must be a JSON object"]
    errors = sorted(_validator().iter_errors(spec), key=lambda item: list(item.absolute_path))
    messages = [f"{_error_path(error)}: {error.message}" for error in errors[:_MAX_ERRORS]]
    if len(errors) > _MAX_ERRORS:
        messages.append(f"... {len(errors) - _MAX_ERRORS} more errors")
    return messages


def parse_spec(data: bytes) -> tuple[dict[str, Any] | None, list[str]]:
    """Decode and validate spec bytes. Returns (spec, errors)."""
    try:
        spec = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, [f"Dashboard file is not valid JSON: {exc}"]
    errors = validate_spec(spec)
    return (spec if not errors else None), errors


def dataset_definitions(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    definitions = spec.get("datasets")
    if not isinstance(definitions, dict):
        return {}
    return {str(name): value for name, value in definitions.items() if isinstance(value, dict)}


def static_rows(definition: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Rows of a static dataset, or None when the dataset is SQL."""
    rows = definition.get("rows")
    if rows is None:
        return None
    if not isinstance(rows, list):
        return []
    return [dict(item) for item in rows if isinstance(item, dict)]


def dataset_sql(spec: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """{dataset name: (connection, sql)} for every SQL dataset."""
    result: dict[str, tuple[str, str]] = {}
    for name, definition in dataset_definitions(spec).items():
        if static_rows(definition) is not None:
            continue
        connection = str(definition.get("connection") or "").strip()
        sql = str(definition.get("sql") or "").strip()
        if connection and sql:
            result[name] = (connection, sql)
    return result


def snapshot_path(name: str) -> str:
    """Where a chat keeps the cached result of a SQL dataset."""
    return f"{SNAPSHOT_DIR}/{name}.csv"


def dataset_file_refs(spec: dict[str, Any]) -> dict[str, str]:
    """{dataset name: snapshot path} for every SQL dataset."""
    return {name: snapshot_path(name) for name in dataset_sql(spec)}


def chart_count(spec: dict[str, Any]) -> int:
    charts = spec.get("charts")
    return len(charts) if isinstance(charts, list) else 0
