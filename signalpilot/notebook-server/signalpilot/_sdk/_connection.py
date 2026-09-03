"""Connection object — user-facing interface to a SignalPilot data connection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from signalpilot._sdk._client import GatewayClient


@dataclass(frozen=True)
class DatasetRef:
    id: str
    schema: tuple[dict[str, Any], ...]
    row_count: int
    byte_size: int
    completeness: str
    expires_at: str
    _client: GatewayClient = field(repr=False, compare=False)


class Connection:
    """A handle to a named database connection on the SignalPilot gateway."""

    def __init__(self, name: str, client: GatewayClient):
        self._name = name
        self._client = client

    def query(self, sql: str, row_limit: int = 1000) -> list[dict[str, Any]]:
        """Execute a governed SQL query. Compatibility wrapper returning rows."""
        return self.query_result(sql, row_limit).get("rows", [])

    def query_result(
        self,
        sql: str,
        row_limit: int = 100_000,
    ) -> dict[str, Any]:
        """Transparently plan and run a governed notebook query."""
        data = self._client.post(
            "/api/query",
            {
                "connection_name": self._name,
                "sql": sql,
                "row_limit": row_limit,
            },
            headers={"X-SP-Query-Path": "sdk"},
        )
        return data

    def query_dataset(self, sql: str) -> DatasetRef:
        """Transparently plan and stream a private, expiring Parquet object."""
        data = self._client.post(
            "/api/query/datasets",
            {"connection_name": self._name, "sql": sql},
            timeout=3600,
            headers={"X-SP-Query-Path": "sdk"},
        )
        return DatasetRef(
            id=str(data["dataset_id"]),
            schema=tuple(data.get("schema") or ()),
            row_count=int(data["row_count"]),
            byte_size=int(data["byte_size"]),
            completeness=str(data["completeness"]),
            expires_at=str(data["expires_at"]),
            _client=self._client,
        )

    def tables(self, filter: str | None = None) -> list[dict[str, Any]]:  # noqa: A002
        """List tables in this connection."""
        params: dict[str, Any] = {}
        if filter:
            params["filter"] = filter
        data = self._client.get(f"/api/connections/{self._name}/schema", params or None)
        if isinstance(data, list):
            return data
        return data.get("tables", data.get("schema", []))

    def describe(self, table: str) -> list[dict[str, Any]]:
        """Column details for a table — types, stats, annotations."""
        data = self._client.get(
            f"/api/connections/{self._name}/schema/explore-table",
            {"table_name": table},
        )
        return data.get("columns", data) if isinstance(data, dict) else data

    def explain(self, sql: str) -> dict[str, Any]:
        """Query plan and cost estimate without executing."""
        return self._client.post("/api/query/explain", {
            "connection_name": self._name,
            "sql": sql,
        })

    def sample_values(self, table: str, column: str, limit: int = 50) -> list[Any]:
        """Distinct sample values for a column."""
        data = self._client.get(
            f"/api/connections/{self._name}/schema/sample-values",
            {"table_name": table, "column_name": column, "limit": limit},
        )
        if isinstance(data, list):
            return data
        return data.get("values", data.get("samples", []))

    def join_path(self, from_table: str, to_table: str, max_hops: int = 4) -> list[dict[str, Any]]:
        """Find join path between two tables via foreign keys."""
        data = self._client.get(
            f"/api/connections/{self._name}/schema/join-paths",
            {"from": from_table, "to": to_table, "max_hops": max_hops},
        )
        if isinstance(data, list):
            return data
        return data.get("paths", data.get("joins", []))

    def schema_overview(self) -> dict[str, Any]:
        """High-level schema summary — table counts, sizes, etc."""
        return self._client.get(f"/api/connections/{self._name}/schema/overview")

    def __repr__(self) -> str:
        return f"Connection({self._name!r})"
