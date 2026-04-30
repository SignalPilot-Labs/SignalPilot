"""MCP tool call model."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, model_validator

_MCP_ARGUMENTS_MAX_DEPTH: int = 20
_MCP_ARGUMENTS_MAX_SIZE_BYTES: int = 100_000


def _check_dict_depth(obj: Any, current_depth: int, max_depth: int) -> None:
    """Check that obj does not exceed max_depth nesting levels.

    Raises ValueError if current_depth exceeds max_depth BEFORE recursing into
    children, ensuring the Python call stack is never blown even by deeply
    nested inputs.
    """
    if current_depth > max_depth:
        raise ValueError(f"arguments nesting depth exceeds maximum of {max_depth} levels")
    if isinstance(obj, dict):
        for value in obj.values():
            _check_dict_depth(value, current_depth + 1, max_depth)
    elif isinstance(obj, list):
        for item in obj:
            _check_dict_depth(item, current_depth + 1, max_depth)


class MCPToolCall(BaseModel):
    tool: str = Field(..., max_length=128)
    arguments: dict[str, Any] = {}
    session_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _validate_arguments(self) -> MCPToolCall:
        serialized = json.dumps(self.arguments)
        if len(serialized) > _MCP_ARGUMENTS_MAX_SIZE_BYTES:
            raise ValueError(f"arguments serialized size exceeds maximum of {_MCP_ARGUMENTS_MAX_SIZE_BYTES} bytes")
        _check_dict_depth(self.arguments, current_depth=0, max_depth=_MCP_ARGUMENTS_MAX_DEPTH)
        return self
