"""Pure SQL identifier quoting helpers."""

from __future__ import annotations


# Mirrors BaseConnector._quote_identifier (base.py:63-68).
# Duplicated here because the API layer does not have a connector instance
# at the point of SQL construction.
def _quote_identifier(name: str, quote_char: str) -> str:
    """Quote a single SQL identifier, escaping embedded quote characters."""
    if quote_char == "[":
        return "[" + name.replace("]", "]]") + "]"
    return quote_char + name.replace(quote_char, quote_char + quote_char) + quote_char


def _quote_table_name(table: str, quote_char: str) -> str:
    """Quote a possibly schema-qualified table name (e.g., 'public.users')."""
    return ".".join(_quote_identifier(p, quote_char) for p in table.split("."))
