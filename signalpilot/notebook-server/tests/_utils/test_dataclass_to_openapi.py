"""Dataclass defaults in the OpenAPI converter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from signalpilot._utils.dataclass_to_openapi import PythonTypeToOpenAPI


@dataclass
class _Inner:
    count: int = 0


@dataclass
class _Args:
    session_id: str
    preview_lines: int = 3
    include_stderr: bool = False
    tags: list[str] = field(default_factory=list)
    inner: _Inner = field(default_factory=_Inner)
    note: str | None = None


def _convert(*, honor_defaults: bool) -> dict[str, Any]:
    converter = PythonTypeToOpenAPI(
        name_overrides={}, camel_case=False, honor_defaults=honor_defaults
    )
    return converter.convert(_Args, processed_classes={})


def test_defaults_are_emitted_and_not_required() -> None:
    schema = _convert(honor_defaults=True)
    assert schema["required"] == ["session_id"]
    assert schema["properties"]["preview_lines"] == {
        "type": "integer",
        "default": 3,
    }
    assert schema["properties"]["include_stderr"]["default"] is False
    assert schema["properties"]["tags"]["default"] == []
    # A dataclass factory value is not JSON-safe: no default, still optional.
    assert "default" not in schema["properties"]["inner"]
    assert schema["properties"]["note"]["default"] is None


def test_default_behaviour_is_unchanged_without_the_flag() -> None:
    schema = _convert(honor_defaults=False)
    assert schema["required"] == [
        "session_id",
        "preview_lines",
        "include_stderr",
        "tags",
        "inner",
    ]
    assert all("default" not in prop for prop in schema["properties"].values())
