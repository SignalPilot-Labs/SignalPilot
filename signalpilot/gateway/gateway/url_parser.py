"""Unified connection URL parser for all supported database types.

Single source of truth for parsing connection strings into structured fields.
Used by:
- POST /connections/parse-url (API endpoint)
- store.create_connection (backfill metadata from connection_string)
- Any future code that needs to decompose a connection URL
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# Scheme → canonical db_type mapping
SCHEME_MAP: dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "mysql": "mysql",
    "mysql+pymysql": "mysql",
    "mssql": "mssql",
    "mssql+pymssql": "mssql",
    "sqlserver": "mssql",
    "redshift": "redshift",
    "clickhouse": "clickhouse",
    "clickhouse+http": "clickhouse",
    "clickhouse+https": "clickhouse",
    "clickhouses": "clickhouse",
    "snowflake": "snowflake",
    "databricks": "databricks",
    "trino": "trino",
    "trino+https": "trino",
}


def parse_connection_url(url: str, db_type: str = "") -> dict[str, Any]:
    """Parse a database connection URL into individual credential fields.

    Args:
        url: The connection URL string (e.g., postgresql://user:pass@host:5432/db?sslmode=require)
        db_type: Optional db_type hint. If empty, auto-detected from URL scheme.

    Returns:
        Dict of parsed fields. Keys vary by db_type but always include at least
        ``db_type``, ``host``, ``port``, ``username``. Empty/None values are omitted.
    """
    url = url.strip()
    if not url:
        return {}

    # Extract and normalize scheme
    original_scheme = url.split("://")[0] if "://" in url else ""

    if not db_type and original_scheme:
        db_type = SCHEME_MAP.get(original_scheme, "")

    # Replace scheme with http:// so stdlib urlparse handles it correctly
    normalized = url
    if "://" in normalized:
        scheme_part = normalized.split("://")[0]
        normalized = "http://" + normalized[len(scheme_part) + 3:]

    try:
        parsed = urlparse(normalized)
    except Exception:
        return {"db_type": db_type} if db_type else {}

    path_parts = [p for p in (parsed.path or "").split("/") if p]
    query_params = parse_qs(parsed.query or "")

    # Common fields
    result: dict[str, Any] = {
        "db_type": db_type,
        "host": parsed.hostname or "",
        "port": parsed.port,
        "username": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
    }

    # ── Dialect-specific parsing ─────────────────────────────────────────

    if db_type in ("postgres", "redshift"):
        result["database"] = path_parts[0] if path_parts else ""
        sslmode = query_params.get("sslmode", [""])[0]
        if sslmode:
            result["ssl"] = sslmode != "disable"
            result["ssl_mode"] = sslmode

    elif db_type == "mysql":
        result["database"] = path_parts[0] if path_parts else ""

    elif db_type == "mssql":
        result["database"] = path_parts[0] if path_parts else "master"

    elif db_type == "snowflake":
        result["account"] = parsed.hostname or ""
        result["host"] = ""  # Snowflake uses account, not host
        result["database"] = path_parts[0] if len(path_parts) > 0 else ""
        result["schema_name"] = path_parts[1] if len(path_parts) > 1 else ""
        result["warehouse"] = query_params.get("warehouse", [""])[0]
        result["role"] = query_params.get("role", [""])[0]

    elif db_type == "clickhouse":
        result["database"] = path_parts[0] if path_parts else "default"
        if "http" in original_scheme:
            result["protocol"] = "http"
        else:
            result["protocol"] = "native"

    elif db_type == "databricks":
        result["host"] = parsed.hostname or ""
        result["access_token"] = unquote(parsed.username or "")
        result["username"] = ""
        result["password"] = ""
        result["http_path"] = "/".join(path_parts) if path_parts else ""
        result["catalog"] = query_params.get("catalog", [""])[0]
        result["schema_name"] = query_params.get("schema", [""])[0]

    elif db_type == "trino":
        result["catalog"] = path_parts[0] if len(path_parts) > 0 else ""
        result["schema_name"] = path_parts[1] if len(path_parts) > 1 else ""

    else:
        # Unknown db_type — best-effort: extract database from path
        result["database"] = path_parts[0] if path_parts else ""

    # Strip empty/None values
    return {k: v for k, v in result.items() if v is not None and v != ""}


def detect_db_type(url: str) -> str | None:
    """Detect db_type from a connection URL scheme. Returns None if unrecognized."""
    url = url.strip().lower()
    if "://" not in url:
        return None
    scheme = url.split("://")[0]
    return SCHEME_MAP.get(scheme)
