"""Query forwarder for the dbt-proxy.

Mirrors the acquire path from gateway/api/query.py:43-86 exactly:

    info = await store.get_connection(claims.connector_name)
    if info.db_type != "postgres": raise NonPostgresConnector
    conn_str = await store.get_connection_string(claims.connector_name)
    extras   = await store.get_credential_extras(claims.connector_name)
    async with pool_manager.acquire(...) as conn:
        result = await conn.execute(sql)

All SQL passes through validate_dbt_statement() before execution.
Returns row data and column metadata for the session layer to encode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..connectors.pool_manager import pool_manager
from ..engine.dbt_validation import ValidatedStatement, validate_dbt_statement
from ..store import Store
from .audit import record as audit_record
from .errors import NonPostgresConnector
from .tokens import RunTokenClaims

logger = logging.getLogger(__name__)

_POSTGRES_DB_TYPE = "postgres"


@dataclass
class QueryResult:
    """Result of a forwarded dbt query."""

    columns: list[tuple[str, int]]  # (name, type_oid)
    rows: list[list[str | None]]
    command_tag: str


async def execute_query(
    claims: RunTokenClaims,
    sql: str,
    *,
    store: Store,
) -> QueryResult:
    """Execute a governance-checked SQL statement against the connector.

    Raises NonPostgresConnector if the connector is not postgres-typed.
    Calls validate_dbt_statement; if blocked, writes the audit row and re-raises
    as a ValueError with the block_reason so the session can emit ErrorResponse.

    All statements — including those that are blocked — produce exactly one
    audit row via audit.record().
    """
    validation: ValidatedStatement = validate_dbt_statement(sql, claims=claims)

    if validation.blocked:
        await audit_record(
            claims,
            sql,
            blocked=True,
            block_reason=validation.block_reason,
            kind=validation.kind,
            store=store,
        )
        raise ValueError(validation.block_reason or "blocked")

    info = await store.get_connection(claims.connector_name)
    if info is None:
        raise ValueError(f"Connector '{claims.connector_name}' not found")

    if info.db_type != _POSTGRES_DB_TYPE:
        raise NonPostgresConnector(
            f"Connector '{claims.connector_name}' is type '{info.db_type}'; only postgres is supported"
        )

    conn_str = await store.get_connection_string(claims.connector_name)
    if not conn_str:
        raise ValueError(f"No credentials for connector '{claims.connector_name}'")

    extras = await store.get_credential_extras(claims.connector_name)
    connector = await pool_manager.acquire(info.db_type, conn_str, credential_extras=extras)

    try:
        rows_raw = await connector.execute(sql)
    finally:
        await pool_manager.release(info.db_type, conn_str)

    await audit_record(
        claims,
        sql,
        blocked=False,
        block_reason=None,
        kind=validation.kind,
        store=store,
    )

    # rows_raw is a list of dicts from the connector
    if rows_raw and isinstance(rows_raw[0], dict):
        col_names = list(rows_raw[0].keys())
        columns = [(name, 25) for name in col_names]  # OID 25 = text
        rows = [[str(row[col]) if row[col] is not None else None for col in col_names] for row in rows_raw]
    else:
        columns = []
        rows = []

    # Build command tag
    sql_upper = sql.strip().upper()
    if sql_upper.startswith(("SELECT", "WITH")):
        tag = f"SELECT {len(rows)}"
    elif sql_upper.startswith("INSERT"):
        tag = f"INSERT 0 {len(rows)}"
    elif sql_upper.startswith("UPDATE"):
        tag = f"UPDATE {len(rows)}"
    elif sql_upper.startswith("DELETE"):
        tag = f"DELETE {len(rows)}"
    elif sql_upper.startswith("CREATE"):
        tag = "CREATE TABLE"
    elif sql_upper.startswith("DROP"):
        tag = "DROP TABLE"
    elif sql_upper.startswith("ALTER"):
        tag = "ALTER TABLE"
    elif sql_upper.startswith(("BEGIN", "START")):
        tag = "BEGIN"
    elif sql_upper.startswith("COMMIT"):
        tag = "COMMIT"
    elif sql_upper.startswith("ROLLBACK"):
        tag = "ROLLBACK"
    else:
        tag = "OK"

    return QueryResult(columns=columns, rows=rows, command_tag=tag)


__all__ = ["QueryResult", "execute_query"]
