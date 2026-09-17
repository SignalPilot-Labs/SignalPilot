"""Every notebook tool schema is valid JSON Schema and honours defaults."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import jsonschema

# The test conftest stubs signalpilot/__init__.py. Importing the UI plugins
# first mirrors what that init does and avoids the get_datasets import cycle
# the tools registry hits otherwise.
import signalpilot._plugins.ui  # noqa: F401
from signalpilot._server.ai.notebook_mcp import notebook_tool_schemas
from signalpilot._server.ai.tools.registry import (
    SUPPORTED_BACKEND_AND_MCP_TOOLS,
)


def _schemas() -> dict[str, dict[str, Any]]:
    context = SimpleNamespace(app=None)
    instances = {}
    for tool_cls in SUPPORTED_BACKEND_AND_MCP_TOOLS:
        inst = tool_cls(context)
        instances[inst.name] = inst
    return notebook_tool_schemas(instances)


def test_every_tool_schema_is_valid_json_schema() -> None:
    schemas = _schemas()
    assert len(schemas) == len(SUPPORTED_BACKEND_AND_MCP_TOOLS)
    for name, schema in schemas.items():
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object", name
        for required in schema.get("required", []):
            assert required in schema["properties"], (name, required)


def test_lightweight_cell_map_no_longer_requires_preview_lines() -> None:
    schema = _schemas()["get_lightweight_cell_map"]
    assert schema["required"] == ["session_id"]
    assert schema["properties"]["preview_lines"]["default"] == 3
    jsonschema.validate({"session_id": "s"}, schema)


def test_defaulted_arguments_validate_when_omitted() -> None:
    for name, schema in _schemas().items():
        minimal = {
            key: _example(prop)
            for key, prop in schema["properties"].items()
            if key in schema.get("required", [])
        }
        jsonschema.validate(minimal, schema)
        assert "session_id" in schema["properties"] or name in {
            "get_active_notebooks",
            "get_signalpilot_rules",
        }


def _example(prop: dict[str, Any]) -> Any:
    kind = prop.get("type")
    if kind == "string":
        return "x"
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return True
    if kind == "array":
        return []
    return {}
