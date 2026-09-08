"""Dashboard spec schema: the bundled copy and validation helpers.

``dashboard.schema.json`` next to this module is a byte-identical copy of
``signalpilot-plugin/skills/dashboard/dashboard.schema.json``. A test asserts
the identity; update both files together.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("dashboard.schema.json")

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


def dataset_file_refs(spec: dict[str, Any]) -> dict[str, str]:
    """{dataset name: file path} for every dataset backed by a file."""
    refs: dict[str, str] = {}
    for name, definition in dataset_definitions(spec).items():
        file_ref = definition.get("file")
        if isinstance(file_ref, str) and file_ref:
            refs[name] = file_ref
    return refs


def dataset_sources(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{dataset name: source} for every dataset that records how it was produced."""
    sources: dict[str, dict[str, Any]] = {}
    for name, definition in dataset_definitions(spec).items():
        source = definition.get("source")
        if isinstance(source, dict) and source.get("kind"):
            sources[name] = source
    return sources


def chart_count(spec: dict[str, Any]) -> int:
    charts = spec.get("charts")
    return len(charts) if isinstance(charts, list) else 0


