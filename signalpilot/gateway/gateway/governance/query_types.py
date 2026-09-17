"""Governed query types and the typed row encoding shared by every path.

A fresh execution and a replay of the same ``sql_hash`` must hand callers the
same Python types. Rows are therefore encoded exactly once, with
``encode_rows``, and both the durable copy and the in-memory result carry
that encoding: numbers stay numbers (``Decimal`` becomes ``int`` or
``float``), temporal values become ISO 8601 strings, and bytes become
base64. ``columns[].logical_type`` records the driver's original type so a
reader can re-hydrate dates and timestamps when it needs them.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from gateway.db.models import GatewayStructuredQueryResult
from gateway.standalone_chat.object_storage import chat_object_storage

GATEWAY_DB_UNAVAILABLE = "gateway_db_unavailable"
GATEWAY_DB_UNAVAILABLE_MESSAGE = "SignalPilot's own database was unavailable; retry"


class GovernedQueryError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class GovernedQueryContext:
    path: Literal["direct_api", "mcp", "sdk", "dashboard"]
    conversation_id: str | None = None
    run_id: str | None = None
    project_id: str | None = None
    commit_sha: str | None = None
    branch: str | None = None
    plan_id: str | None = None


@dataclass(frozen=True)
class GovernedQueryResult:
    execution_id: str
    result_id: str
    rows: list[dict[str, Any]]
    row_count: int
    tables: list[str]
    execution_ms: float
    sql_hash: str
    completeness: str
    truncation_reason: str | None
    columns: list[dict[str, Any]]
    estimated_cost_usd: float
    estimate_warning: str | None
    pii_redacted: list[str]


def logical_type(value: Any) -> str:
    """Name the driver's type for one sample value before encoding."""
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, (float, Decimal)):
        return "number"
    if isinstance(value, datetime):
        return "timestamp"
    if isinstance(value, date):
        return "date"
    if isinstance(value, time):
        return "time"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "bytes"
    return type(value).__name__.lower()


def encode_value(value: Any) -> Any:
    """Return a JSON-native value that keeps numbers numeric."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            return float(value)
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): encode_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [encode_value(item) for item in value]
    return str(value)


def encode_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{str(key): encode_value(item) for key, item in row.items()} for row in rows]


def describe_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Column descriptors from the raw driver rows (before encoding)."""
    columns: list[dict[str, Any]] = []
    if not rows:
        return columns
    for name in rows[0]:
        values = [row.get(name) for row in rows]
        sample = next((value for value in values if value is not None), None)
        columns.append(
            {
                "name": str(name),
                "logical_type": logical_type(sample),
                "nullable": any(value is None for value in values),
            }
        )
    return columns


def actual_scan_bytes(stats: dict[str, Any]) -> int | None:
    for key in ("total_bytes_processed", "total_bytes_billed", "bytes_scanned", "scanned_bytes"):
        value = stats.get(key)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
    return None


async def load_stored_rows(result: GatewayStructuredQueryResult) -> list[dict[str, Any]]:
    """Return the durable rows of a stored result; they are already typed."""
    if result.storage_kind != "object":
        return list(result.rows_json or [])
    if not result.object_key:
        raise GovernedQueryError("result_unavailable", "Stored query result is unavailable")
    data = await chat_object_storage().get_bytes(result.object_key, max_bytes=10 * 1024 * 1024)
    if result.content_hash and hashlib.sha256(data).hexdigest() != result.content_hash:
        raise GovernedQueryError("result_integrity_failed", "Stored query result failed integrity validation")
    rows = json.loads(data)
    if not isinstance(rows, list):
        raise GovernedQueryError("result_unavailable", "Stored query result is invalid")
    return rows
