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



# Rendered size above which list_tables drops the column lists. It sits under
# the generic 40,000-character result budget in mcp/audit.py so a listing is
# narrowed here, with a hint, instead of being cut mid-line there.
LIST_TABLES_CHAR_BUDGET = 36_000
LIST_TABLES_DEFAULT_MAX = 200


def _row_label(row_count: int) -> str:
    if row_count >= 1_000_000:
        return f"{row_count / 1_000_000:.1f}M rows"
    if row_count >= 1_000:
        return f"{row_count / 1_000:.0f}K rows"
    if row_count > 0:
        return f"{row_count} rows"
    return ""


def _table_line(key: str, table: dict, fk_map: dict[str, str], *, columns: bool) -> str:
    """One table as ``key (rows): cols`` or, compact, ``key (rows, N cols)``."""
    row_label = _row_label(int(table.get("row_count") or 0))
    table_columns = table.get("columns", [])
    if not columns:
        parts = [part for part in (row_label, f"{len(table_columns)} cols") if part]
        return f"{key} ({', '.join(parts)})"
    col_parts = []
    for col in table_columns:
        name = col["name"]
        if col.get("primary_key"):
            name += "*"
        fk_ref = fk_map.get(f"{key}.{col['name']}")
        if fk_ref:
            name += f"→{fk_ref}"
        col_parts.append(name)
    row_str = f" ({row_label})" if row_label else ""
    return f"{key}{row_str}: {', '.join(col_parts)}"


def _render_table_listing(
    schema: dict,
    *,
    header: str,
    max_tables: int,
    columns: bool,
    budget: int = LIST_TABLES_CHAR_BUDGET,
) -> str:
    """Render tables within ``max_tables`` and ``budget`` characters.

    Order of degradation: drop column lists, then drop tables. The last line
    always says how many tables are missing and how to narrow the call.
    """
    fk_map: dict[str, str] = {}
    for key, table in schema.items():
        for fk in table.get("foreign_keys", []):
            fk_map[f"{key}.{fk['column']}"] = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"
    keys = sorted(schema.keys())
    selected = keys[: max(0, max_tables)]
    head = [header, f"Tables: {len(schema)}", ""]

    def render(with_columns: bool) -> list[str]:
        return [_table_line(key, schema[key], fk_map, columns=with_columns) for key in selected]

    body = render(columns)
    if columns and sum(len(line) + 1 for line in head + body) > budget:
        body = render(False)
    # Keep room for the closing hint so the whole reply stays within budget.
    tail_reserve = len(_missing_line(len(keys))) + 1
    used = sum(len(line) + 1 for line in head)
    shown = 0
    for line in body:
        if used + len(line) + 1 > budget - tail_reserve:
            break
        used += len(line) + 1
        shown += 1
    body = body[:shown]
    missing = len(keys) - shown
    if missing > 0:
        body.append(_missing_line(missing))
    return "\n".join(head + body)


def _missing_line(missing: int) -> str:
    return f"{missing} more tables not shown; narrow with schema= or name_contains="


def _filter_schema(schema: dict, *, schema_name: str | None, name_contains: str | None) -> dict:
    wanted_schema = (schema_name or "").strip().lower()
    needle = (name_contains or "").strip().lower()
    filtered = {}
    for key, table in schema.items():
        if wanted_schema and str(table.get("schema") or "").lower() != wanted_schema:
            continue
        if needle and needle not in str(table.get("name") or "").lower():
            continue
        filtered[key] = table
    return filtered


@audited_tool(mcp)
async def list_tables(
    connection_name: str,
    database: str | None = None,
    schema: str | None = None,
    name_contains: str | None = None,
    max_tables: int = LIST_TABLES_DEFAULT_MAX,
    columns: bool = True,
) -> str:
    """
    List the tables of a database connection, one line per table.

    Each line shows the table, its row count, and its column names. A
    primary key column ends with ``*``. A foreign key column shows its
    target after an arrow. Read this first. Then call describe_table for
    the tables that matter.

    Some connections hold many databases (a whole SQL Server or Trino
    cluster). For those, call this tool with no database first. The reply
    lists the databases and their table counts. Then call it again with the
    database name.

    Narrow a large listing. Pass schema to keep one schema. Pass
    name_contains to keep tables whose name contains that text. Set
    columns=false to get only names and counts. The reply never exceeds
    about 36,000 characters: when it would, the tool drops the column lists,
    then drops tables, and the last line says how many tables are missing.

    Args:
        connection_name: Name of a configured database connection.
        database: In a multi-database connection, list only this database.
            Omit it to list the databases.
        schema: Keep only tables in this schema. The match ignores case.
        name_contains: Keep only tables whose name contains this text. The
            match ignores case.
        max_tables: Maximum number of tables in the reply. Default 200.
        columns: Include column names. Default true. Set false for a compact
            listing of names and counts.

    Returns:
        A table listing as text.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if max_tables < 1:
        return "Error: max_tables must be at least 1"

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

        full_schema = schema_cache.get(connection_name)
        if full_schema is None:
            from gateway.connectors.pool_manager import pool_manager

            try:
                async with pool_manager.connection(
                    conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                ) as connector:
                    full_schema = await connector.get_schema()
            except Exception as e:
                return f"Error: Could not fetch schema: {sanitize_mcp_error(str(e))}"
            schema_cache.put(connection_name, full_schema)

        # Multi-database connections (SQL Server, Trino, etc.) tag each table
        # with its database. A whole-cluster listing can be ~1MB of text, which
        # is unusable context and can overrun the tool-response transport. So:
        # list the databases first, and only expand one database's tables when
        # the caller names it.
        databases: dict[str, int] = {}
        for table in full_schema.values():
            db_name = table.get("database")
            if db_name:
                databases[db_name] = databases.get(db_name, 0) + 1

        # Format parsed by standalone_chat/tool_projection/schema.py; update tests there if you change this
        tables = full_schema
        if databases:
            if database is None:
                db_lines = [
                    f"Connection: {connection_name} ({conn_info.db_type})",
                    f"This connection has {len(databases)} databases and "
                    f"{len(full_schema)} tables total.",
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
            tables = {k: t for k, t in full_schema.items() if t.get("database") == database}

        tables = _filter_schema(tables, schema_name=schema, name_contains=name_contains)
        header = (
            f"Database: {database} ({conn_info.db_type})"
            if database
            else f"Database: {connection_name} ({conn_info.db_type})"
        )
        return _render_table_listing(tables, header=header, max_tables=max_tables, columns=columns)
    finally:
        current_org_id_var.reset(token)
