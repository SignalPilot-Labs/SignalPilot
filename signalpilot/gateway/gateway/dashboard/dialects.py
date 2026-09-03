"""Connector-owned SQL compilation rules for governed dashboards."""

from __future__ import annotations

from dataclasses import dataclass

from gateway.governance.bindings import ParameterStyle, parameter_token


class DashboardDialectError(ValueError):
    pass


@dataclass(frozen=True)
class DashboardDialect:
    db_type: str
    sqlglot_name: str
    parameter_style: ParameterStyle
    identifier_quote: str
    text_type: str
    max_relation_parts: int = 3
    top_limit: bool = False
    case_insensitive_search: bool = False
    lower_search: bool = False

    def quote_identifier(self, value: str) -> str:
        if not value or "\x00" in value:
            raise DashboardDialectError(f"Invalid {self.db_type} identifier")
        if self.identifier_quote == "[":
            return "[" + value.replace("]", "]]") + "]"
        quote = self.identifier_quote
        return quote + value.replace(quote, quote + quote) + quote

    def quote_relation(self, value: str) -> str:
        parts = value.split(".")
        if not 1 <= len(parts) <= self.max_relation_parts or any(not part for part in parts):
            raise DashboardDialectError(f"Invalid {self.db_type} relation")
        return ".".join(self.quote_identifier(part) for part in parts)

    def parameter(self, index: int) -> str:
        return parameter_token(index)

    def search_predicate(self, expression: str, parameter: str) -> str:
        cast = f"CAST({expression} AS {self.text_type})"
        if self.case_insensitive_search:
            return f"{cast} ILIKE {parameter}"
        if self.lower_search:
            return f"LOWER({cast}) LIKE LOWER({parameter})"
        return f"{cast} LIKE {parameter}"

    def distinct_values_sql(
        self,
        *,
        column: str,
        relation: str,
        predicate: str,
        alias: str,
        limit: int,
    ) -> str:
        select = "SELECT DISTINCT"
        suffix = f" LIMIT {limit}"
        if self.top_limit:
            select += f" TOP {limit}"
            suffix = ""
        return f"{select} {column} AS {alias} FROM {relation}{predicate} ORDER BY {alias}{suffix}"


MSSQL_DIALECT = DashboardDialect("mssql", "tsql", ParameterStyle.FORMAT, "[", "NVARCHAR(4000)", top_limit=True)
POSTGRES_DIALECT = DashboardDialect(
    "postgres",
    "postgres",
    ParameterStyle.NUMERIC_DOLLAR,
    '"',
    "TEXT",
    max_relation_parts=2,
    case_insensitive_search=True,
)
DUCKDB_DIALECT = DashboardDialect(
    "duckdb", "duckdb", ParameterStyle.QMARK, '"', "VARCHAR", case_insensitive_search=True
)
MYSQL_DIALECT = DashboardDialect("mysql", "mysql", ParameterStyle.FORMAT, "`", "CHAR", max_relation_parts=2)
SNOWFLAKE_DIALECT = DashboardDialect(
    "snowflake", "snowflake", ParameterStyle.FORMAT, '"', "VARCHAR", case_insensitive_search=True
)
BIGQUERY_DIALECT = DashboardDialect("bigquery", "bigquery", ParameterStyle.QMARK, "`", "STRING", lower_search=True)
REDSHIFT_DIALECT = DashboardDialect(
    "redshift",
    "redshift",
    ParameterStyle.FORMAT,
    '"',
    "VARCHAR",
    max_relation_parts=2,
    case_insensitive_search=True,
)
CLICKHOUSE_DIALECT = DashboardDialect(
    "clickhouse", "clickhouse", ParameterStyle.NAMED_PYFORMAT, "`", "String", lower_search=True
)
DATABRICKS_DIALECT = DashboardDialect(
    "databricks", "databricks", ParameterStyle.QMARK, "`", "STRING", lower_search=True
)
TRINO_DIALECT = DashboardDialect("trino", "trino", ParameterStyle.QMARK, '"', "VARCHAR", lower_search=True)
SQLITE_DIALECT = DashboardDialect("sqlite", "sqlite", ParameterStyle.QMARK, '"', "TEXT", max_relation_parts=2)
XATA_DIALECT = DashboardDialect(
    "xata",
    "postgres",
    ParameterStyle.NUMERIC_DOLLAR,
    '"',
    "TEXT",
    max_relation_parts=2,
    case_insensitive_search=True,
)
