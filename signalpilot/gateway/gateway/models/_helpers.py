"""Private helpers shared across gateway/models/ leaf modules."""

from __future__ import annotations


def _validate_string_list(v: list[str], max_item_len: int, field_name: str) -> list[str]:
    """Validate that each item in a string list does not exceed max_item_len."""
    for item in v:
        if len(item) > max_item_len:
            raise ValueError(f"Each item in {field_name} must be at most {max_item_len} characters")
    return v
