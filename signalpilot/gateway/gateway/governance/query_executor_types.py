"""Shared types for the governed query executor and its phase modules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

import sqlglot


class GovernedQueryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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


def normalize_sql(sql: str, dialect: str | None) -> str:
    """Produce the canonical SQL used by durable hashes and approvals."""
    try:
        expression = sqlglot.parse_one(sql, read=dialect)
        return expression.sql(dialect=dialect, pretty=False, normalize=True)
    except Exception:
        return re.sub(r"\s+", " ", sql.strip().rstrip(";"))
