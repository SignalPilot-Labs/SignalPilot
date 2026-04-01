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

    async def get_sample_values(self, table: str, columns: list[str], limit: int = 5) -> dict[str, list]:
        """Return sample distinct values for specified columns.

        Helps LLM agents understand column semantics for schema linking.
        Default implementation uses a generic SQL query.
        """
        return {}
