"""Locate and cache the dashboard JSON schema; validate dashboard specs.

The schema file is the single contract shared by the agent skill, the web
renderer, and these tools. It lives in the agent plugin at
``skills/dashboard/dashboard.schema.json``. At runtime the plugin root comes
from ``SP_AGENT_PLUGIN_PATH``; in tests the repo checkout is found by walking
up from this file.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_RELATIVE_PATH = Path("skills") / "dashboard" / "dashboard.schema.json"
_MAX_ERRORS = 50

# Tool-argument patterns. The chart id pattern is the schema's ``$defs.id``.
DASHBOARD_PATH_PATTERN = r"^artifacts/[A-Za-z0-9_./-]+\.dashboard\.json$"
CHART_ID_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class DashboardSchemaUnavailable(RuntimeError):
    """Raised when no schema file can be located or parsed."""


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    plugin_path = os.getenv("SP_AGENT_PLUGIN_PATH", "").strip()
    if plugin_path:
        candidates.append(Path(plugin_path) / SCHEMA_RELATIVE_PATH)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "signalpilot-plugin" / SCHEMA_RELATIVE_PATH)
    return candidates


def locate_schema_file() -> Path:
    """Return the first schema file that exists.

    Raises:
        DashboardSchemaUnavailable: when no candidate exists.
    """
    for candidate in _candidate_paths():
        if candidate.is_file():
            return candidate
    raise DashboardSchemaUnavailable(
        "dashboard.schema.json was not found. Set SP_AGENT_PLUGIN_PATH to "
        "the agent plugin root."
    )


@lru_cache(maxsize=4)
def _load_validator(schema_path: str) -> Any:
    from jsonschema import Draft202012Validator

    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DashboardSchemaUnavailable(
            f"dashboard.schema.json could not be read: {exc}"
        ) from exc
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_validator() -> Any:
    """Return the cached ``Draft202012Validator`` for the dashboard schema."""
    return _load_validator(str(locate_schema_file()))


def _json_path(error: Any) -> str:
    parts = ["$"]
    for element in error.absolute_path:
        if isinstance(element, int):
            parts.append(f"[{element}]")
        else:
            parts.append(f".{element}")
    return "".join(parts)


def validate_spec(obj: Any) -> list[str]:
    """Validate a parsed dashboard document.

    Returns a list of human-readable messages, each prefixed with the JSON
    path of the offending value. An empty list means the document is valid.
    Never raises for a bad document; raises only when the schema itself is
    unavailable.
    """
    from jsonschema.exceptions import best_match

    validator = schema_validator()
    messages: list[str] = []
    errors = sorted(
        validator.iter_errors(obj),
        key=lambda error: list(map(str, error.absolute_path)),
    )
    for error in errors:
        chosen = best_match([error]) or error
        messages.append(f"{_json_path(chosen)}: {chosen.message}")
        if len(messages) >= _MAX_ERRORS:
            break
    return messages
