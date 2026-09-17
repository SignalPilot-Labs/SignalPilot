"""Connection object: the user-facing interface to a SignalPilot data connection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from signalpilot._sdk._client import GatewayClient

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pandas as pd

# Gateway ``columns[].logical_type`` values that hold numbers or times. The
# replay cache serialises Decimal, date and datetime as strings, so the
# frame coerces by logical type rather than by the value's Python type.
NUMERIC_LOGICAL_TYPES = frozenset(
    {"integer", "int", "number", "float", "decimal", "numeric", "bigint"}
)
DATETIME_LOGICAL_TYPES = frozenset(
    {"timestamp", "datetime", "date", "timestamptz"}
)


@dataclass(frozen=True)
class DatasetRef:
    id: str
    schema: tuple[dict[str, Any], ...]
    row_count: int
    byte_size: int
    completeness: str
    expires_at: str
    _client: GatewayClient = field(repr=False, compare=False)


class QueryRows(list):
    """Rows from ``db.query`` with the gateway column schema attached.

    Behaves as the plain list of row dicts it always was: integer and slice
    indexing, iteration and ``len`` are unchanged. ``rows["rows"]`` returns
    the list itself so code written against the old ``query_result`` shape
    keeps working. ``.columns`` holds the gateway schema and ``.df()``
    builds a typed pandas DataFrame.
    """

    def __init__(
        self,
        rows: Iterable[dict[str, Any]] = (),
        columns: Iterable[dict[str, Any]] = (),
    ) -> None:
        super().__init__(rows)
        self.columns: list[dict[str, Any]] = [dict(c) for c in columns]

    @property
    def rows(self) -> QueryRows:
        return self

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            if key == "rows":
                return self
            if key == "columns":
                return self.columns
            raise KeyError(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def df(self) -> pd.DataFrame:
        """A pandas DataFrame with columns coerced by gateway logical type."""
        import pandas as pd

        names = [str(c.get("name")) for c in self.columns if c.get("name")]
        frame = pd.DataFrame(list(self), columns=names or None)
        return coerce_frame(frame, self.columns)

    def __repr__(self) -> str:
        return f"QueryRows({list.__repr__(self)}, columns={self.columns!r})"


def coerce_frame(frame: pd.DataFrame, columns: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Coerce ``frame`` columns in place by the gateway ``logical_type``."""
    import pandas as pd

    for column in columns:
        name = column.get("name")
        logical = str(column.get("logical_type") or "").lower()
        if name not in frame.columns:
            continue
        if logical in NUMERIC_LOGICAL_TYPES:
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
        elif logical in DATETIME_LOGICAL_TYPES:
            frame[name] = pd.to_datetime(frame[name], errors="coerce")
    return frame


class Connection:
    """A handle to a named database connection on the SignalPilot gateway."""

    def __init__(self, name: str, client: GatewayClient):
        self._name = name
        self._client = client

    @property
    def name(self) -> str:
        """The connection name on the gateway."""
        return self._name

    def query(self, sql: str, row_limit: int = 1000) -> QueryRows:
        """Execute a governed SQL query and return the rows.

        The result is a list of row dicts with ``.columns`` and ``.df()``.
        """
        data = self.query_result(sql, row_limit)
        return QueryRows(data.get("rows") or [], data.get("columns") or [])

    def query_df(self, sql: str, row_limit: int = 1000) -> pd.DataFrame:
        """Execute a governed SQL query and return a typed pandas DataFrame."""
        return self.query(sql, row_limit).df()

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
        """Column details for a table: types, stats, annotations."""
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
        """High-level schema summary: table counts, sizes, etc."""
        return self._client.get(f"/api/connections/{self._name}/schema/overview")

    def __repr__(self) -> str:
        return f"Connection({self._name!r})"
