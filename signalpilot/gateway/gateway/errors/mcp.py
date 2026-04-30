"""MCP-specific error sanitization helpers.

LLM agent clients receive different error trade-offs than HTTP clients:
- DB errors must retain enough diagnostic text for agent self-correction (Spider2.0 SOTA pattern)
- Infrastructure errors (sandbox URLs, connection strings) are genericized
- All errors are capped and stripped of secrets/paths
"""

from __future__ import annotations

import re

# Keep in sync with api/deps._SENSITIVE_PATTERNS
# Duplication is intentional — importing private symbols across module boundaries is fragile.
# The test in test_mcp_error_sanitization.py asserts these lists match.
_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"postgresql://[^\s]+", re.IGNORECASE),
    re.compile(r"mysql://[^\s]+", re.IGNORECASE),
    re.compile(r"redshift://[^\s]+", re.IGNORECASE),
    re.compile(r"clickhouse://[^\s]+", re.IGNORECASE),
    re.compile(r"snowflake://[^\s]+", re.IGNORECASE),
    re.compile(r"databricks://[^\s]+", re.IGNORECASE),
    re.compile(r"password[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"host=\S+", re.IGNORECASE),
    re.compile(r"access_token[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"private_key[=:]\s*\S+", re.IGNORECASE),
]

# MCP-specific path patterns: MCP tools interact with the filesystem (dbt projects, source files)
_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"/home/[^\s,;)\"']+"),
    re.compile(r"/var/[^\s,;)\"']+"),
    re.compile(r"/opt/[^\s,;)\"']+"),
    re.compile(r"/tmp/[^\s,;)\"']+"),
    re.compile(r"/etc/[^\s,;)\"']+"),
    re.compile(r"C:\\[^\s,;)\"']+", re.IGNORECASE),
]

# Python traceback frame pattern
_TRACEBACK_FRAME_RE = re.compile(r'File "[^"]+", line \d+')


def sanitize_mcp_error(error: str, *, cap: int = 200) -> str:
    """Sanitize an exception message for return to an LLM agent client.

    Applies sensitive pattern redaction, path stripping, traceback frame
    stripping, and length capping. Preserves enough diagnostic text for
    agent self-correction on DB errors (Spider2.0 SOTA pattern).

    Args:
        error: Raw exception string to sanitize.
        cap: Maximum length of the returned string (default 200).

    Returns:
        Sanitized string, at most `cap` characters long.
    """
    sanitized = error

    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)

    for pattern in _PATH_PATTERNS:
        sanitized = pattern.sub("[path]", sanitized)

    sanitized = _TRACEBACK_FRAME_RE.sub("[traceback]", sanitized)

    if len(sanitized) > cap:
        sanitized = sanitized[:cap] + "..."

    return sanitized


def sanitize_proxy_response(status_code: int, body: str, *, cap: int = 200) -> str:
    """Format and sanitize a REST API proxy response for return to an LLM agent client.

    The REST API may return JSON with internal details in error responses.
    This function redacts sensitive content and caps the body length.

    Args:
        status_code: HTTP status code from the proxied REST API call.
        body: Raw response body text from the proxied call.
        cap: Maximum length of the sanitized body (default 200).

    Returns:
        Formatted string: "Error ({status_code}): {sanitized_body}"
    """
    sanitized_body = sanitize_mcp_error(body, cap=cap)
    return f"Error ({status_code}): {sanitized_body}"
