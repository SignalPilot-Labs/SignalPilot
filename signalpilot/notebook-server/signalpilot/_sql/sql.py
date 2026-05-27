# Copyright 2026 SignalPilot. All rights reserved.
from __future__ import annotations

import os
from typing import Any, Literal, cast

from signalpilot._dependencies.dependencies import DependencyManager
from signalpilot._output.rich_help import mddoc
from signalpilot._runtime.output import replace
from signalpilot._sql.engines.dbapi import DBAPIConnection, DBAPIEngine
from signalpilot._sql.engines.duckdb import DuckDBEngine
from signalpilot._sql.engines.sqlalchemy import SQLAlchemyEngine
from signalpilot._sql.engines.types import QueryEngine
from signalpilot._sql.error_utils import SpSQLException, is_sql_parse_error
from signalpilot._sql.get_engines import SUPPORTED_ENGINES
from signalpilot._sql.utils import (
    extract_explain_content,
    is_explain_query,
    raise_df_import_error,
)
from signalpilot._types.ids import VariableName
from signalpilot._utils.narwhals_utils import can_narwhalify_lazyframe


def get_default_result_limit() -> int | None:
    limit = os.environ.get("SP_SQL_DEFAULT_LIMIT")
    return int(limit) if limit is not None else None


@mddoc
def sql(
    query: str,
    *,
    output: bool = True,
    engine: DBAPIConnection | str | None = None,
) -> Any:
    """
    Execute a SQL query.

    When a SignalPilot Gateway is configured (SP_API_KEY set), queries route through
    the gateway. Pass a connection name as a string to target a specific database.

    You can also pass a DB-API 2.0 compatible connection object for direct execution.

    Args:
        query: The SQL query to execute.
        output: Whether to display the result in the UI. Defaults to True.
        engine: A SignalPilot Gateway connection name (string), a DB-API 2.0 compatible
            connection object, or None to use the default gateway connection.

    Returns:
        The result of the query as a DataFrame.
    """
    if query is None or query.strip() == "":
        return None

    # If engine is a string, route through SignalPilot Gateway
    if isinstance(engine, str):
        return _execute_via_gateway(query, engine, output)

    sql_engine: QueryEngine[Any]
    if engine is None:
        # Try gateway first if configured, fall back to local DuckDB
        from signalpilot._gateway import get_gateway_client

        client = get_gateway_client()
        if client is not None:
            try:
                connections = client.list_connections()
                if connections:
                    return _execute_via_gateway(
                        query, connections[0]["name"], output
                    )
            except Exception:
                pass

        DependencyManager.require_many(
            "to execute sql",
            DependencyManager.duckdb,
            DependencyManager.sqlglot,
            source="kernel",
        )
        sql_engine = DuckDBEngine(connection=None)
    else:
        for engine_cls in SUPPORTED_ENGINES:
            if engine_cls.is_compatible(engine):
                sql_engine = engine_cls(
                    connection=engine, engine_name=VariableName("custom")
                )  # type: ignore
                break
        else:
            raise ValueError(
                "Unsupported engine. Must be a SQLAlchemy, Ibis, Clickhouse, DuckDB, Redshift, StarRocks or DBAPI 2.0 compatible engine, "
                "or a string connection name for SignalPilot Gateway."
            )

    try:
        df = sql_engine.execute(query)
    except Exception as e:
        if is_sql_parse_error(e):
            raise SpSQLException(
                message=str(e),
                sql_statement=query,
                sql_line=None,
                sql_col=None,
                hint=None,
            ) from e
        raise

    if df is None:
        return None

    has_limit = False
    try:
        default_result_limit = get_default_result_limit()
        if default_result_limit is not None:
            has_limit = _query_includes_limit(query)
    except OSError:
        default_result_limit = None

    enforce_own_limit = not has_limit and default_result_limit is not None

    custom_total_count: Literal["too_many"] | None = None
    if enforce_own_limit:
        if DependencyManager.polars.has():
            custom_total_count = (
                "too_many"
                if len(df) > cast(int, default_result_limit)
                else None
            )
            df = df.limit(default_result_limit)
        elif DependencyManager.pandas.has():
            custom_total_count = (
                "too_many"
                if len(df) > cast(int, default_result_limit)
                else None
            )
            df = df.head(default_result_limit)
        else:
            raise_df_import_error("polars[pyarrow]")

    if output:
        from signalpilot._output.formatters.df_formatters import include_opinionated
        from signalpilot._output.formatting import plain
        from signalpilot._plugins.stateless.plain_text import plain_text
        from signalpilot._plugins.ui._impl import table

        if isinstance(sql_engine, DuckDBEngine) and is_explain_query(query):
            # For EXPLAIN queries in DuckDB, display plain output to preserve box drawings
            text_output = extract_explain_content(df)
            replace(plain_text(text_output))
        elif not include_opinionated():
            # Respect display.dataframes config - use plain formatting
            replace(plain(df))
        elif can_narwhalify_lazyframe(df):
            # For pl.LazyFrame and DuckDBRelation, we only show the first few rows
            # to avoid loading all the data into memory.
            # Also preload the first page of data without user confirmation.
            replace(table.table.lazy(df, preload=True))
        else:
            # df may be a cursor result from an SQL Engine
            # In this case, we need to convert it to a DataFrame
            display_df = df
            if SQLAlchemyEngine.is_cursor_result(df):
                display_df = SQLAlchemyEngine.get_cursor_metadata(df)
            elif DBAPIEngine.is_dbapi_cursor(df):
                display_df = DBAPIEngine.get_cursor_metadata(df)

            replace(
                table.table(
                    display_df,
                    selection=None,
                    pagination=True,
                    _internal_total_rows=custom_total_count,
                )
            )
    return df


def _execute_via_gateway(
    query: str, connection_name: str, output: bool
) -> Any:
    """Execute SQL through SignalPilot Gateway and return a DataFrame."""
    from signalpilot._gateway import get_gateway_client
    from signalpilot._gateway.client import GatewayError, GatewayUnavailable

    client = get_gateway_client()
    if client is None:
        raise ValueError(
            "SignalPilot Gateway not configured. Set SP_API_KEY in your .env file."
        )

    try:
        result = client.execute_query(
            connection_name=connection_name,
            sql=query,
            row_limit=10000,
            timeout_seconds=60,
        )
    except GatewayUnavailable as e:
        raise ConnectionError(
            f"SignalPilot Gateway is not reachable: {e}"
        ) from e
    except GatewayError as e:
        raise SpSQLException(
            message=f"Gateway query error: {e.body}",
            sql_statement=query,
            sql_line=None,
            sql_col=None,
            hint=None,
        ) from e

    rows = result.get("rows", [])
    if not rows:
        return None

    if DependencyManager.polars.has():
        import polars as pl

        df = pl.DataFrame(rows)
    elif DependencyManager.pandas.has():
        import pandas as pd

        df = pd.DataFrame(rows)
    else:
        return rows

    if output:
        from signalpilot._output.formatters.df_formatters import include_opinionated
        from signalpilot._output.formatting import plain
        from signalpilot._plugins.ui._impl import table as table_mod

        if include_opinionated():
            replace(
                table_mod.table(
                    df,
                    selection=None,
                    pagination=True,
                )
            )
        else:
            replace(plain(df))

    return df


def _query_includes_limit(query: str) -> bool:
    """Check if a SQL query includes a LIMIT clause."""
    import sqlglot
    from sqlglot.expressions import Limit, Select

    try:
        expressions = sqlglot.parse(query.strip())
    except Exception:
        # May not be valid SQL
        return False

    if not expressions:
        return False

    # Only check the last statement in case of multiple statements
    last_expr = expressions[-1]
    if not isinstance(last_expr, Select):
        return False

    # Look for any LIMIT clause in the SELECT statement
    return last_expr.find(Limit) is not None
