"""Schema catalog tools: describe_table, list_tables (tools 1, 2)."""

from gateway.errors.mcp import sanitize_mcp_error
from gateway.governance.context import current_org_id_var
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session, mcp_org_id_var
from gateway.mcp.server import mcp
from gateway.mcp.validation import _validate_connection_name


@audited_tool(mcp)
async def describe_table(connection_name: str, table_name: str) -> str:
    """
    Get detailed column information for a specific database table.

    Returns column names, types, nullability, and any annotations
    (descriptions, PII flags) from the schema.yml file.

    Args:
        connection_name: Name of a configured database connection
        table_name: Name of the table to describe

    Returns:
        Column details as formatted text.
    """
    # Input validation
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

    from gateway.governance.annotations import load_annotations

    async with _store_session() as store:
        tool_org_id: str = store.org_id or "local"
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

        # Check schema cache first (Feature #18) — inside session so contextvar is set
        from gateway.connectors.schema_cache import schema_cache

        schema = schema_cache.get(connection_name)
        if schema is None:
            from gateway.connectors.pool_manager import pool_manager

            try:
                async with pool_manager.connection(
                    conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                ) as connector:
                    schema = await connector.get_schema()
            except Exception as e:
                return f"Error: Could not fetch schema: {sanitize_mcp_error(str(e))}"
            schema_cache.put(connection_name, schema)

    # Find the table (case-insensitive)
    table_data = None
    for _key, val in schema.items():
        if val.get("name", "").lower() == table_name.lower():
            table_data = val
            break

    if not table_data:
        table_names = [v.get("name", k) for k, v in schema.items()]
        return f"Table '{table_name}' not found. Available tables:\n" + "\n".join(
            f"  - {t}" for t in sorted(table_names)
        )

    # Load annotations for descriptions/PII info
    annotations = load_annotations(tool_org_id, connection_name)
    table_ann = annotations.get_table(table_name)

    # Format parsed by standalone_chat/tool_projection/schema.py; update tests there if you change this
    lines = [f"Table: {table_data['schema']}.{table_data['name']}"]
    if table_ann and table_ann.description:
        lines.append(f"Description: {table_ann.description}")
    if table_ann and table_ann.owner:
        lines.append(f"Owner: {table_ann.owner}")
    lines.append(f"Columns ({len(table_data['columns'])}):")
    lines.append("")

    for col in table_data["columns"]:
        nullable = "nullable" if col.get("nullable") else "NOT NULL"
        pk = " [PK]" if col.get("primary_key") else ""
        line = f"  {col['name']} — {col['type']} ({nullable}){pk}"

        # Add annotation info
        if table_ann and col["name"] in table_ann.columns:
            col_ann = table_ann.columns[col["name"]]
            if col_ann.description:
                line += f"\n    {col_ann.description}"
            if col_ann.pii:
                line += f"\n    [PII: {col_ann.pii}]"

        lines.append(line)

    return "\n".join(lines)


@audited_tool(mcp)
async def list_tables(connection_name: str, database: str | None = None) -> str:
    """
    List tables in a database with compact schema overview.

    Returns a one-line-per-table summary with column names, primary keys,
    foreign keys, and row counts. This is designed for schema linking —
    read this first, then use describe_table for details on relevant tables.

    Some connections span many databases (a whole SQL Server or Trino cluster).
    For those, call with no database first to get the list of databases and
    their table counts, then call again with a database name to see that
    database's tables. This keeps each result small.

    Args:
        connection_name: Name of a configured database connection
        database: Optional. In a multi-database connection, list only this
            database's tables. Omit to list databases to choose from.

    Returns:
        Compact table listing optimized for LLM context efficiency.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

    org_id = mcp_org_id_var.get(None) or "local"
    token = current_org_id_var.set(org_id)
    try:
        from gateway.connectors.schema_cache import schema_cache

        schema = schema_cache.get(connection_name)
        if schema is None:
            from gateway.connectors.pool_manager import pool_manager

            try:
                async with pool_manager.connection(
                    conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                ) as connector:
                    schema = await connector.get_schema()
            except Exception as e:
                return f"Error: Could not fetch schema: {sanitize_mcp_error(str(e))}"
            schema_cache.put(connection_name, schema)

        # Multi-database connections (SQL Server, Trino, etc.) tag each table
        # with its database. A whole-cluster listing can be ~1MB of text, which
        # is unusable context and can overrun the tool-response transport. So:
        # list the databases first, and only expand one database's tables when
        # the caller names it.
        databases: dict[str, int] = {}
        for table in schema.values():
            db_name = table.get("database")
            if db_name:
                databases[db_name] = databases.get(db_name, 0) + 1

        # Format parsed by standalone_chat/tool_projection/schema.py; update tests there if you change this
        if databases:
            if database is None:
                db_lines = [
                    f"Connection: {connection_name} ({conn_info.db_type})",
                    f"This connection has {len(databases)} databases and "
                    f"{len(schema)} tables total.",
                    "Call list_tables again with a database name to see its "
                    "tables. Databases (table counts):",
                    "",
                ]
                for db_name in sorted(databases):
                    db_lines.append(f"  {db_name} ({databases[db_name]} tables)")
                return "\n".join(db_lines)
            if database not in databases:
                available = ", ".join(sorted(databases))
                return (
                    f"Error: database '{database}' not found in connection "
                    f"'{connection_name}'. Available databases: {available}"
                )
            # Keep only this database's tables. Multi-db keys are
            # "database.schema.table"; each entry also carries a "database" tag.
            schema = {k: t for k, t in schema.items() if t.get("database") == database}

        # Build FK lookup
        fk_map: dict[str, str] = {}
        for key, table in schema.items():
            for fk in table.get("foreign_keys", []):
                fk_map[f"{key}.{fk['column']}"] = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"

        header = (
            f"Database: {database} ({conn_info.db_type})"
            if database
            else f"Database: {connection_name} ({conn_info.db_type})"
        )
        lines = [header, f"Tables: {len(schema)}", ""]
        for key in sorted(schema.keys()):
            table = schema[key]
            row_count = table.get("row_count", 0)
            if row_count >= 1_000_000:
                row_str = f" ({row_count / 1_000_000:.1f}M rows)"
            elif row_count >= 1_000:
                row_str = f" ({row_count / 1_000:.0f}K rows)"
            elif row_count > 0:
                row_str = f" ({row_count} rows)"
            else:
                row_str = ""

            col_parts = []
            for col in table.get("columns", []):
                name = col["name"]
                if col.get("primary_key"):
                    name += "*"
                fk_ref = fk_map.get(f"{key}.{col['name']}")
                if fk_ref:
                    name += f"→{fk_ref}"
                col_parts.append(name)

            lines.append(f"{key}{row_str}: {', '.join(col_parts)}")

        return "\n".join(lines)
    finally:
        current_org_id_var.reset(token)
