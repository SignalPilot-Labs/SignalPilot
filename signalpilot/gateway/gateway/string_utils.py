"""Small string coercion helpers shared by gateway modules."""

from __future__ import annotations

from typing import Any


def string_value(value: Any) -> str:
    return value if isinstance(value, str) else ""


def optional_string_value(value: Any) -> str | None:
    return str(value) if value else None
