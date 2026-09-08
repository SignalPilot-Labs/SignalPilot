"""Connector-owned parameter binding rules for governed query execution."""

from __future__ import annotations

from dataclasses import dataclass

from gateway.governance.bindings import ParameterStyle, parameter_token


class ConnectorDialectError(ValueError):
    pass


@dataclass(frozen=True)
class ConnectorDialect:
    db_type: str
    sqlglot_name: str
    parameter_style: ParameterStyle
    identifier_quote: str

    def quote_identifier(self, value: str) -> str:
        if not value or "\x00" in value:
            raise ConnectorDialectError(f"Invalid {self.db_type} identifier")
        if self.identifier_quote == "[":
            return "[" + value.replace("]", "]]") + "]"
        quote = self.identifier_quote
        return quote + value.replace(quote, quote + quote) + quote

    def parameter(self, index: int) -> str:
        return parameter_token(index)


MSSQL_DIALECT = ConnectorDialect("mssql", "tsql", ParameterStyle.FORMAT, "[")
POSTGRES_DIALECT = ConnectorDialect("postgres", "postgres", ParameterStyle.NUMERIC_DOLLAR, '"')
DUCKDB_DIALECT = ConnectorDialect("duckdb", "duckdb", ParameterStyle.QMARK, '"')
MYSQL_DIALECT = ConnectorDialect("mysql", "mysql", ParameterStyle.FORMAT, "`")
SNOWFLAKE_DIALECT = ConnectorDialect("snowflake", "snowflake", ParameterStyle.FORMAT, '"')
BIGQUERY_DIALECT = ConnectorDialect("bigquery", "bigquery", ParameterStyle.QMARK, "`")
REDSHIFT_DIALECT = ConnectorDialect("redshift", "redshift", ParameterStyle.FORMAT, '"')
CLICKHOUSE_DIALECT = ConnectorDialect("clickhouse", "clickhouse", ParameterStyle.NAMED_PYFORMAT, "`")
DATABRICKS_DIALECT = ConnectorDialect("databricks", "databricks", ParameterStyle.QMARK, "`")
TRINO_DIALECT = ConnectorDialect("trino", "trino", ParameterStyle.QMARK, '"')
SQLITE_DIALECT = ConnectorDialect("sqlite", "sqlite", ParameterStyle.QMARK, '"')
XATA_DIALECT = ConnectorDialect("xata", "postgres", ParameterStyle.NUMERIC_DOLLAR, '"')
