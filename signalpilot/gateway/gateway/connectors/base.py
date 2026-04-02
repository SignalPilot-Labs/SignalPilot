"""Base connector interface — every DB connector implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """Abstract base class for all database connectors."""

    @abstractmethod
    async def connect(self, connection_string: str) -> None:
        """Open connection pool."""

    @abstractmethod
    async def execute(self, sql: str, params: list | None = None, timeout: int | None = None) -> list[dict[str, Any]]:
        """Execute query and return rows as list of dicts.

        Args:
            sql: SQL query string
            params: Optional query parameters
            timeout: Per-query timeout in seconds (Feature #8). The query is
                     cancelled on the DB side (not just client-side) when exceeded.
        """

    @abstractmethod
    async def get_schema(self) -> dict[str, Any]:
        """Return schema info: tables with columns."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if connection is healthy."""

    @abstractmethod
    async def close(self) -> None:
        """Close connection pool."""

    def set_credential_extras(self, extras: dict) -> None:
        """Set structured credential data for the connection.

        Override in subclasses that need structured auth beyond a connection string
        (e.g., SSL certs, service account JSON, SSH tunnel config).
        Called by PoolManager before connect().
        """
        pass

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Return sample distinct values for specified columns.

        Helps LLM agents understand column semantics for schema linking.
        Default implementation uses a generic SQL query.
        """
        return {}

    @staticmethod
    def _build_sample_union_sql(
        table: str, columns: list[str], limit: int = 5, quote: str = '"'
    ) -> str:
        """Build a UNION ALL query to fetch sample values for multiple columns in one round trip.

        Returns SQL like:
          SELECT 'col1' AS _col, CAST("col1" AS VARCHAR) AS _val FROM (SELECT DISTINCT "col1" FROM tbl WHERE "col1" IS NOT NULL LIMIT 5) t
          UNION ALL
          SELECT 'col2' AS _col, CAST("col2" AS VARCHAR) AS _val FROM (SELECT DISTINCT "col2" FROM tbl WHERE "col2" IS NOT NULL LIMIT 5) t
        """
        parts = []
        for i, col in enumerate(columns[:20]):
            q = quote
            parts.append(
                f"SELECT '{col}' AS _col, CAST({q}{col}{q} AS VARCHAR) AS _val "
                f"FROM (SELECT DISTINCT {q}{col}{q} FROM {table} WHERE {q}{col}{q} IS NOT NULL LIMIT {limit}) t{i}"
            )
        return "\n UNION ALL \n".join(parts)

    @staticmethod
    def _parse_sample_union_result(rows: list[dict] | list[tuple]) -> dict[str, list]:
        """Parse UNION ALL sample query result into {column: [values]} dict."""
        result: dict[str, list] = {}
        for row in rows:
            if isinstance(row, dict):
                col, val = row.get("_col", ""), row.get("_val", "")
            else:
                col, val = row[0], row[1]
            if col and val is not None:
                if col not in result:
                    result[col] = []
                result[col].append(str(val))
        return result
