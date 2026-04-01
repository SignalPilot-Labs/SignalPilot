"""Base connector interface — every DB connector implements this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConnectionTestResult:
    """Rich result from testing a database connection."""

    healthy: bool
    message: str
    latency_ms: float = 0.0
    server_version: str | None = None
    database_name: str | None = None
    table_count: int | None = None
    schema_preview: list[dict[str, Any]] = field(default_factory=list)
    ssl_active: bool = False
    max_connections: int | None = None
    current_connections: int | None = None
    server_uptime: str | None = None
    error_code: str | None = None
    error_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


class BaseConnector(ABC):
    """Abstract base class for all database connectors.

    Each connector manages its own connection lifecycle and must support:
      - Connecting with timeout and optional SSL
      - Read-only query execution with parameter binding
      - Schema introspection
      - Rich health checking with server metadata
      - Graceful cleanup
    """

    # Default timeouts (seconds)
    CONNECT_TIMEOUT: float = 10.0
    QUERY_TIMEOUT: float = 30.0

    @abstractmethod
    async def connect(
        self,
        connection_string: str,
        *,
        connect_timeout: float | None = None,
        ssl: bool = False,
    ) -> None:
        """Open connection pool with timeout and optional SSL."""

    @abstractmethod
    async def execute(
        self,
        sql: str,
        params: list | None = None,
        *,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """Execute a read-only query and return rows as list of dicts."""

    @abstractmethod
    async def get_schema(self) -> dict[str, Any]:
        """Return schema info: tables with columns, types, and nullability."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if connection is healthy."""

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        """Perform a comprehensive connection test returning rich metadata.

        This goes beyond health_check by collecting server version, table count,
        schema preview, SSL status, and other diagnostic information useful for
        the connection setup UX.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close connection pool and release all resources."""

    @staticmethod
    def friendly_error(error: Exception) -> tuple[str, str | None]:
        """Convert a raw exception into a user-friendly (message, hint) tuple.

        Subclasses should override to provide database-specific error messages.
        """
        msg = str(error)
        hint = None

        # Common patterns
        if "could not connect" in msg.lower() or "connection refused" in msg.lower():
            hint = "Check that the database server is running and the host/port are correct."
        elif "password" in msg.lower() or "authentication" in msg.lower():
            hint = "Verify your username and password are correct."
        elif "does not exist" in msg.lower() and "database" in msg.lower():
            hint = "The database name may be incorrect. Check the database field."
        elif "timeout" in msg.lower():
            hint = "The connection timed out. The server may be overloaded or unreachable."
        elif "ssl" in msg.lower():
            hint = "Try toggling the SSL setting, or check your SSL certificate configuration."

        return msg, hint
