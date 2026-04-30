"""Schema summary tool: schema_overview (tool 7)."""

from __future__ import annotations

import httpx

from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers, _store_session
from gateway.mcp.server import mcp
from gateway.mcp.validation import _CONN_NAME_RE
from gateway.mcp_errors import sanitize_mcp_error, sanitize_proxy_response


@audited_tool(mcp)
async def schema_overview(connection_name: str) -> str:
    """
    Quick database overview — table count, columns, rows, FK density.

    Use this first to understand the database before loading schema.
    Returns a recommendation for which schema format to use.

    Args:
        connection_name: Name of the database connection
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    try:
        async with httpx.AsyncClient(base_url=_gateway_url(), timeout=30) as client:
            resp = await client.get(f"/api/connections/{connection_name}/schema/overview", headers=_gw_headers())
            if resp.status_code != 200:
                return sanitize_proxy_response(resp.status_code, resp.text)
            data = resp.json()

        lines = [
            f"Database: {connection_name} ({data.get('db_type', 'unknown')})",
            f"Schemas: {', '.join(data.get('schemas', []))}",
            f"Tables: {data.get('table_count', 0)}",
            f"Columns: {data.get('total_columns', 0)} (avg {data.get('avg_columns_per_table', 0)} per table)",
            f"Total rows: {data.get('total_rows', 0):,}",
            f"Foreign keys: {data.get('total_foreign_keys', 0)} across {data.get('tables_with_fks', 0)} tables",
            f"Recommended schema format: {data.get('recommendation', 'enriched')}",
        ]

        largest = data.get("largest_tables", [])
        if largest:
            lines.append("\nLargest tables:")
            for t in largest[:5]:
                lines.append(f"  {t['table']}: {t['rows']:,} rows, {t['columns']} cols, {t['fks']} FKs")

        return "\n".join(lines)

    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    # Fallback: use local connector when gateway is unavailable
    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    from gateway.connectors.pool_manager import pool_manager
    from gateway.connectors.schema_cache import schema_cache

    schema = schema_cache.get(connection_name)
    if schema is None:
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                schema = await connector.get_schema()
        except Exception as e:
            return f"Error: Could not fetch schema: {sanitize_mcp_error(str(e))}"
        schema_cache.put(connection_name, schema)

    fk_map: dict[str, str] = {}
    for key, table in schema.items():
        for fk in table.get("foreign_keys", []):
            fk_map[f"{key}.{fk['column']}"] = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"

    total_rows = sum(t.get("row_count", 0) for t in schema.values())
    total_columns = sum(len(t.get("columns", [])) for t in schema.values())
    total_fks = sum(len(t.get("foreign_keys", [])) for t in schema.values())
    tables_with_fks = sum(1 for t in schema.values() if t.get("foreign_keys"))

    lines = [
        "Note: Using direct connector (gateway unavailable).",
        "",
        f"Database: {connection_name} ({conn_info.db_type})",
        f"Tables: {len(schema)}",
        f"Columns: {total_columns}",
        f"Total rows: {total_rows:,}",
        f"Foreign keys: {total_fks} across {tables_with_fks} tables",
    ]

    largest = sorted(schema.items(), key=lambda kv: kv[1].get("row_count", 0), reverse=True)[:5]
    if largest:
        lines.append("\nLargest tables:")
        for key, table in largest:
            row_count = table.get("row_count", 0)
            col_count = len(table.get("columns", []))
            fk_count = len(table.get("foreign_keys", []))
            lines.append(f"  {key}: {row_count:,} rows, {col_count} cols, {fk_count} FKs")

    return "\n".join(lines)
