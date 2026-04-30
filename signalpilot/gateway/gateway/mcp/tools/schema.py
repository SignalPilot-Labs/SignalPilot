"""Schema tools: describe_table, list_tables, schema_overview, schema_diff, etc."""

from __future__ import annotations

import json

import httpx

from gateway.governance.context import current_org_id_var
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers, _store_session, mcp_org_id_var
from gateway.mcp.helpers import _fetch_date_boundaries
from gateway.mcp.server import mcp
from gateway.mcp.validation import _CONN_NAME_RE, _validate_connection_name
from gateway.mcp_errors import sanitize_mcp_error, sanitize_proxy_response


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
async def list_tables(connection_name: str) -> str:
    """
    List all tables in a database with compact schema overview.

    Returns a one-line-per-table summary with column names, primary keys,
    foreign keys, and row counts. This is designed for schema linking —
    read this first, then use describe_table for details on relevant tables.

    Args:
        connection_name: Name of a configured database connection

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

        # Build FK lookup
        fk_map: dict[str, str] = {}
        for key, table in schema.items():
            for fk in table.get("foreign_keys", []):
                fk_map[f"{key}.{fk['column']}"] = f"{fk.get('references_table', '')}.{fk.get('references_column', '')}"

        lines = [f"Database: {connection_name} ({conn_info.db_type})", f"Tables: {len(schema)}", ""]
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


@audited_tool(mcp)
async def get_date_boundaries(connection_name: str) -> str:
    """
    Get the MIN and MAX dates across all DATE and TIMESTAMP columns in a connection.

    Queries every table to find date column boundaries. Use the returned
    GLOBAL MAX DATE as your date spine endpoint — never use current_date,
    now(), or current_timestamp as a spine endpoint.

    Args:
        connection_name: Name of a configured database connection

    Returns:
        Formatted string with per-table MIN/MAX dates and the global MAX date.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"

    org_id = mcp_org_id_var.get(None) or "local"
    token = current_org_id_var.set(org_id)
    try:
        try:
            result = await _fetch_date_boundaries(connection_name)
        except Exception as e:
            return f"Error: {sanitize_mcp_error(str(e))}"

        if not result.found_any:
            return f"Date boundaries for: {connection_name} ({result.db_type})\nNo DATE or TIMESTAMP columns found in this connection."

        lines = [f"Date boundaries for: {connection_name} ({result.db_type})", ""]

        # Reconstruct per-table detail lines from structured result.
        # We need the schema object to iterate in the same order, so we re-use
        # the table_col_results that _fetch_date_boundaries already collected.
        from gateway.connectors.schema_cache import schema_cache

        schema = schema_cache.get(connection_name) or {}

        DATE_TYPE_KEYWORDS = ("date", "timestamp", "datetime")
        for key in sorted(schema.keys()):
            table = schema[key]
            table_schema = table.get("schema", "")
            table_name = table.get("name", key)
            full_name = f"{table_schema}.{table_name}" if table_schema else table_name
            date_cols = [
                col
                for col in table.get("columns", [])
                if any(kw in col.get("type", "").lower() for kw in DATE_TYPE_KEYWORDS)
            ]
            if not date_cols:
                continue
            col_results = result.table_col_results.get(full_name, {})
            lines.append(f"Table: {full_name}")
            for col in date_cols:
                col_name = col["name"]
                col_type = col.get("type", "")
                if col_name not in col_results:
                    lines.append(f"  {col_name} ({col_type}): (query failed)")
                else:
                    min_val, max_val = col_results[col_name]
                    if min_val is None and max_val is None:
                        lines.append(f"  {col_name} ({col_type}): (no data)")
                    else:
                        lines.append(f"  {col_name} ({col_type}): {min_val} → {max_val}")
            lines.append("")

        if result.global_max:
            lines.append(f"GLOBAL MAX DATE: {result.global_max}")
            lines.append("")

        if result.table_max:
            lines.append("TABLE MAX DATES (use these for date spine endpoints):")
            for tbl, tbl_max in sorted(result.table_max.items()):
                count_str = (
                    f"{result.table_row_count[tbl]:,} rows"
                    if tbl in result.table_row_count
                    else "row count unavailable"
                )
                size_marker = " (largest table)" if tbl == result.largest_table else ""
                spine_marker = (
                    " ← USE THIS for spine if this is your fact/event table" if tbl_max != result.global_max else ""
                )
                lines.append(f"  {tbl} → {tbl_max} ({count_str}){size_marker}{spine_marker}")
            lines.append("")
            lines.append("RULE: Use the max date of your PRIMARY FACT TABLE (orders, events, transactions)")
            lines.append("      as the date spine endpoint. Do NOT use the global max if it comes from a")
            lines.append("      dimension or reference table with a later date.")
        else:
            lines.append("GLOBAL MAX DATE: (no non-null date values found)")

        return "\n".join(lines)
    finally:
        current_org_id_var.reset(token)


@audited_tool(mcp)
async def find_join_path(connection_name: str, from_table: str, to_table: str, max_hops: int = 4) -> str:
    """
    Find join paths between two tables for accurate multi-table SQL generation.

    Returns the exact join columns at each hop, enabling correct JOIN construction
    without hallucinating join conditions. Essential for Spider2.0-style queries.

    Includes both explicit FK relationships AND inferred joins from column naming
    conventions (e.g., customer_id → customers.id), making this work even on
    databases without FK declarations (data lakes, Databricks, ClickHouse, etc.).

    Args:
        connection_name: Name of the database connection
        from_table: Source table (e.g., 'public.orders')
        to_table: Target table (e.g., 'public.products')
        max_hops: Maximum FK hops to search (1-6, default 4)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    async with httpx.AsyncClient(base_url=_gateway_url(), timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/join-paths",
            params={"from_table": from_table, "to_table": to_table, "max_hops": max_hops, "include_implicit": "true"},
            headers=_gw_headers(),
        )
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)
        data = resp.json()

    paths = data.get("paths", [])
    if not paths:
        return f"No join path found between {from_table} and {to_table} within {max_hops} hops"

    lines = [f"Join paths: {from_table} → {to_table} ({len(paths)} found)\n"]
    for i, p in enumerate(paths):
        lines.append(f"Path {i + 1} ({p['hops']} hop{'s' if p['hops'] != 1 else ''}):")
        lines.append(f"  Tables: {' → '.join(p['tables'])}")
        for j in p.get("joins", []):
            lines.append(f"  JOIN ON {j['from']} = {j['to']}")
        if p.get("sql_hint"):
            lines.append(f"  SQL: {p['sql_hint']}")
        lines.append("")
    return "\n".join(lines)


@audited_tool(mcp)
async def get_relationships(connection_name: str, format: str = "compact") -> str:
    """
    Get all foreign key relationships for a connection — ERD overview.

    Useful for understanding the data model before writing queries.
    Returns FK arrows showing which tables reference which.

    Args:
        connection_name: Name of the database connection
        format: Output format — 'compact' (arrows), 'graph' (adjacency list)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    async with httpx.AsyncClient(base_url=_gateway_url(), timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/relationships",
            params={"format": format},
            headers=_gw_headers(),
        )
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)
        data = resp.json()

    if format == "compact":
        rels = data.get("relationships", [])
        if not rels:
            return "No foreign key relationships found"
        header = f"Foreign Key Relationships ({len(rels)}):\n"
        return header + "\n".join(f"  {r}" for r in rels)
    elif format == "graph":
        adj = data.get("adjacency", {})
        if not adj:
            return "No relationships found"
        lines = [f"Table Graph ({len(adj)} tables):\n"]
        for table, neighbors in adj.items():
            lines.append(f"  {table} ↔ {', '.join(neighbors)}")
        return "\n".join(lines)
    else:
        return json.dumps(data, indent=2)


@audited_tool(mcp)
async def explore_table(connection_name: str, table_name: str) -> str:
    """
    Deep-dive a specific table — get full column details, types, FK refs, and sample values.

    Use this after list_tables to investigate tables relevant to the user's question.
    This follows the ReFoRCE iterative column exploration pattern (Spider2.0 SOTA).

    Args:
        connection_name: Name of the database connection
        table_name: Full table name (e.g., 'public.customers')
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    async with httpx.AsyncClient(base_url=_gateway_url(), timeout=30) as client:
        resp = await client.get(
            f"/api/connections/{connection_name}/schema/explore-table",
            params={"table": table_name, "include_samples": True},
            headers=_gw_headers(),
        )
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)
        data = resp.json()

    lines = [f"Table: {data.get('table', table_name)}"]
    row_count = data.get("row_count", 0)
    if row_count:
        lines.append(f"Rows: {row_count:,}")
    if data.get("engine"):
        lines.append(f"Engine: {data['engine']}")
    lines.append("")

    # Columns
    lines.append("Columns:")
    for col in data.get("columns", []):
        parts = [f"  {col['name']}"]
        parts.append(col.get("type", "?"))
        flags = []
        if col.get("primary_key"):
            flags.append("PK")
        if not col.get("nullable", True):
            flags.append("NOT NULL")
        if col.get("foreign_key"):
            fk = col["foreign_key"]
            flags.append(f"FK→{fk['references_table']}.{fk['references_column']}")
        if flags:
            parts.append(f"[{', '.join(flags)}]")
        if col.get("comment"):
            parts.append(f"-- {col['comment']}")
        lines.append(" ".join(parts))

    # Foreign keys
    fks = data.get("foreign_keys", [])
    if fks:
        lines.append(f"\nOutgoing FKs ({len(fks)}):")
        for fk in fks:
            lines.append(f"  {fk['column']} → {fk.get('references_table', '?')}.{fk.get('references_column', '?')}")

    # Referenced by
    refs = data.get("referenced_by", [])
    if refs:
        lines.append(f"\nReferenced by ({len(refs)}):")
        for ref in refs:
            lines.append(f"  {ref['table']}.{ref['column']} → {ref['references_column']}")

    # Sample values
    samples = data.get("sample_values", {})
    if samples:
        lines.append("\nSample values:")
        for col_name, vals in samples.items():
            lines.append(f"  {col_name}: {', '.join(str(v) for v in vals[:5])}")

    return "\n".join(lines)


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


@audited_tool(mcp)
async def schema_diff(connection_name: str) -> str:
    """
    Compare current database schema against the last cached version.

    Returns added/removed/modified tables and columns. Use this after DDL changes
    or migrations to verify what changed and update your understanding of the schema.
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(f"{gw}/api/connections/{connection_name}/schema/diff", headers=_gw_headers())
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    lines = [f"Schema Diff for {connection_name}:"]
    lines.append(f"  Tables: {data.get('table_count', 0)}")

    if not data.get("has_cached"):
        lines.append(f"  {data.get('message', 'No cached schema — baseline stored.')}")
        return "\n".join(lines)

    diff = data.get("diff", {})
    if not diff.get("has_changes"):
        lines.append("  No changes detected")
        return "\n".join(lines)

    added = diff.get("added_tables", [])
    removed = diff.get("removed_tables", [])
    modified = diff.get("modified_tables", [])

    if added:
        lines.append(f"  Added tables ({len(added)}): {', '.join(added[:10])}")
    if removed:
        lines.append(f"  Removed tables ({len(removed)}): {', '.join(removed[:10])}")
    if modified:
        lines.append(f"  Modified tables ({len(modified)}):")
        for m in modified[:5]:
            parts = [m["table"]]
            if m.get("added_columns"):
                parts.append(f"+cols: {', '.join(m['added_columns'][:5])}")
            if m.get("removed_columns"):
                parts.append(f"-cols: {', '.join(m['removed_columns'][:5])}")
            if m.get("type_changes"):
                for tc in m["type_changes"][:3]:
                    parts.append(f"{tc['column']}: {tc['old_type']}→{tc['new_type']}")
            lines.append(f"    {' | '.join(parts)}")

    return "\n".join(lines)


@audited_tool(mcp)
async def schema_ddl(connection_name: str, max_tables: int = 50, compress: bool = False) -> str:
    """
    Get the database schema as CREATE TABLE DDL statements.

    DDL format is preferred over JSON/text for text-to-SQL because:
    - LLMs have seen massive DDL in training, making it the natural schema format
    - DDL encodes constraints (PK, FK, NOT NULL) in standard SQL syntax
    - Spider2.0 SOTA systems (DAIL-SQL, CHESS) use DDL format

    Use this when you need to write SQL queries against the database.
    For initial exploration, use schema_overview first, then compact_schema,
    then this tool for the final DDL needed to write queries.

    Args:
        connection_name: Name of the database connection
        max_tables: Maximum number of tables to include (default 50)
        compress: Enable ReFoRCE-style table grouping for large schemas (groups similar-prefix
                  tables, shows one DDL per group with member list — saves 30-50% tokens)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{gw}/api/connections/{connection_name}/schema/ddl",
            params={"max_tables": max_tables, "compress": compress},
            headers=_gw_headers(),
        )
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    compressed = data.get("compressed_tables", 0)
    total_repr = data.get("total_tables_represented", data.get("table_count", 0))
    header = f"-- Schema DDL for {connection_name}\n-- Tables: {data.get('table_count', 0)} DDL"
    if compressed:
        header += f" + {compressed} compressed ({total_repr} total)"
    header += f", Est. tokens: {data.get('token_estimate', 0)}\n\n"
    return header + data.get("ddl", "")


@audited_tool(mcp)
async def schema_link(connection_name: str, question: str, format: str = "ddl", max_tables: int = 20) -> str:
    """
    Smart schema linking — find tables relevant to a natural language question.

    This is the recommended tool for writing SQL queries. Instead of loading the
    full schema, describe what you want to query and this tool returns only the
    relevant tables with their DDL, scored by relevance.

    Uses high-recall linking (EDBT 2026): matches question terms against table
    names, column names, and comments, then expands via foreign keys to ensure
    join paths are available.

    Args:
        connection_name: Name of the database connection
        question: Natural language question (e.g., "total revenue by customer last month")
        format: Output format — "ddl" (default, best for SQL gen), "compact", or "json"
        max_tables: Maximum tables to include (default 20)
    """
    if not _CONN_NAME_RE.match(connection_name):
        return "Error: Invalid connection name"

    gw = _gateway_url()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{gw}/api/connections/{connection_name}/schema/link",
            params={"question": question, "format": format, "max_tables": max_tables},
            headers=_gw_headers(),
        )
    if r.status_code != 200:
        return sanitize_proxy_response(r.status_code, r.text)

    data = r.json()
    linked = data.get("linked_tables", 0)
    total = data.get("total_tables", 0)
    header = f"-- Schema linked for: {question}\n-- Linked {linked}/{total} tables\n"

    if format == "compact":
        return header + "\n" + data.get("schema", "")
    elif format == "json":
        import json as _json

        return header + "\n" + _json.dumps(data.get("tables", {}), indent=2, default=str)
    else:
        tokens = data.get("token_estimate", 0)
        header += f"-- Est. tokens: {tokens}\n\n"
        return header + data.get("ddl", "")


@audited_tool(mcp)
async def explore_columns(
    connection_name: str,
    table: str,
    columns: list[str] | None = None,
    include_samples: bool = True,
    include_stats: bool = True,
) -> str:
    """
    Explore specific columns in a table — their types, statistics, and sample values.

    Use this for iterative column exploration (ReFoRCE pattern): first use
    schema_link to find relevant tables, then explore_columns to understand
    specific columns before writing SQL.

    Args:
        connection_name: Name of the database connection
        table: Full table name (e.g., "public.customers")
        columns: Optional list of column names to explore. If None, explores all.
        include_samples: Whether to include sample distinct values
        include_stats: Whether to include column statistics

    Returns column details: type, nullable, primary_key, comment, stats, sample values
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    try:
        # Use the deep column exploration endpoint (single API call)
        gw = _gateway_url()
        body: dict = {
            "table": table,
            "include_stats": include_stats,
            "include_values": include_samples,
            "value_limit": 10,
        }
        if columns:
            body["columns"] = columns

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{gw}/api/connections/{connection_name}/schema/explore-columns",
                json=body,
                headers=_gw_headers(),
            )
        if resp.status_code == 404:
            return f"Table '{table}' not found. Check the table name with schema_link first."
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)

        data = resp.json()
        explored_cols = data.get("columns", [])

        # Build response
        table_type = data.get("table_type", "table")
        rc = data.get("row_count", "?")
        lines = [
            f"{'View' if table_type == 'view' else 'Table'}: {table} ({rc:,} rows)"
            if isinstance(rc, int)
            else f"Table: {table} ({rc} rows)"
        ]
        lines.append("")

        for col in explored_cols:
            parts = [f"  {col['name']}: {col.get('type', 'unknown')}"]
            flags = []
            if col.get("primary_key"):
                flags.append("PK")
            if not col.get("nullable", True):
                flags.append("NOT NULL")
            if flags:
                parts.append(f"[{', '.join(flags)}]")
            if col.get("comment"):
                parts.append(f"-- {col['comment']}")
            lines.append(" ".join(parts))

            # Schema statistics (distinct count, cardinality)
            if include_stats and col.get("schema_stats"):
                stats = col["schema_stats"]
                stat_parts = []
                if stats.get("distinct_count"):
                    stat_parts.append(f"distinct={stats['distinct_count']}")
                if stats.get("distinct_fraction"):
                    frac = abs(stats["distinct_fraction"])
                    stat_parts.append(f"uniqueness={frac:.2f}")
                if stat_parts:
                    lines.append(f"    stats: {', '.join(stat_parts)}")

            # Numeric value stats (min/max/avg)
            if include_stats and col.get("value_stats"):
                vs = col["value_stats"]
                vs_parts = []
                if vs.get("min") is not None:
                    vs_parts.append(f"min={vs['min']}")
                if vs.get("max") is not None:
                    vs_parts.append(f"max={vs['max']}")
                if vs.get("avg") is not None:
                    vs_parts.append(f"avg={vs['avg']}")
                if vs_parts:
                    lines.append(f"    range: {', '.join(vs_parts)}")

            # Sample values
            if include_samples and col.get("sample_values"):
                vals = col["sample_values"][:10]
                lines.append(f"    values: {', '.join(repr(v) for v in vals)}")

        return "\n".join(lines)

    except Exception as e:
        return f"Error exploring columns: {sanitize_mcp_error(str(e))}"


@audited_tool(mcp)
async def schema_statistics(connection_name: str) -> str:
    """
    Get a high-level summary of the database schema — table counts, total rows,
    column counts, FK density. Useful for understanding the overall data landscape
    before diving into specific tables.

    Returns: overview with tables sorted by size and FK connectivity.
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    try:
        gw = _gateway_url()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{gw}/api/connections/{connection_name}/schema/overview", headers=_gw_headers())
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)

        data = resp.json()
        lines = [
            f"Database: {connection_name} ({data.get('db_type', '?')})",
            f"Tables: {data.get('table_count', 0)}",
            f"Total columns: {data.get('total_columns', 0)}",
            f"Total rows: {data.get('total_rows', 0):,}",
            f"Foreign key relationships: {data.get('total_foreign_keys', 0)}",
            "",
        ]

        # Show top tables by row count
        top = data.get("largest_tables", [])
        if top:
            lines.append("Largest tables:")
            for t in top[:10]:
                name = t.get("table", "?")
                meta_parts = [f"{t.get('rows', 0):,} rows", f"{t.get('columns', 0)} cols"]
                if t.get("engine"):
                    meta_parts.append(f"engine={t['engine']}")
                if t.get("sorting_key"):
                    meta_parts.append(f"order_by={t['sorting_key']}")
                if t.get("diststyle"):
                    meta_parts.append(f"dist={t['diststyle']}")
                if t.get("sortkey"):
                    meta_parts.append(f"sort={t['sortkey']}")
                if t.get("clustering_key"):
                    meta_parts.append(f"cluster={t['clustering_key']}")
                if t.get("size_bytes") and t["size_bytes"] > 0:
                    mb = t["size_bytes"] / (1024 * 1024)
                    meta_parts.append(f"size={mb:.1f}MB")
                elif t.get("size_mb") and t["size_mb"] > 0:
                    meta_parts.append(f"size={t['size_mb']}MB")
                lines.append(f"  {name}: {', '.join(meta_parts)}")

        # Hub tables (most FK connections — derived from largest_tables)
        hub = sorted([t for t in top if t.get("fks", 0) > 0], key=lambda t: -t.get("fks", 0))
        if hub:
            lines.append("")
            lines.append("Hub tables (most relationships):")
            for t in hub[:5]:
                lines.append(f"  {t.get('table', '?')}: {t.get('fks', 0)} FKs")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"


@audited_tool(mcp)
async def explore_column(
    connection_name: str,
    table: str,
    column: str,
    limit: int = 20,
    filter_pattern: str = "",
) -> str:
    """
    Explore distinct values in a specific column — critical for Spider2.0.

    ReFoRCE-style iterative column exploration: probe actual column values
    to resolve ambiguity when the question uses domain terminology not in
    column names. Returns top distinct values with counts and NULL stats.

    Args:
        connection_name: Database connection to query.
        table: Full table name (e.g., 'public.users' or 'schema.table').
        column: Column name to explore.
        limit: Max distinct values to return (default 20).
        filter_pattern: Optional LIKE pattern to filter values (e.g., '%active%').
    """
    err = _validate_connection_name(connection_name)
    if err:
        return err

    try:
        gw = _gateway_url()
        params = {"table": table, "column": column, "limit": limit}
        if filter_pattern:
            params["filter_pattern"] = filter_pattern

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{gw}/api/connections/{connection_name}/schema/explore",
                params=params,
                headers=_gw_headers(),
            )
        if resp.status_code != 200:
            return sanitize_proxy_response(resp.status_code, resp.text)

        data = resp.json()
        lines = [f"Column: {table}.{column}"]

        stats = data.get("statistics", {})
        lines.append(f"Total rows: {stats.get('total_rows', 0):,}")
        lines.append(f"Distinct values: {stats.get('distinct_count', 0):,}")
        lines.append(f"NULL: {stats.get('null_count', 0):,} ({stats.get('null_pct', 0)}%)")

        if data.get("filter"):
            lines.append(f"Filter: LIKE '{data['filter']}'")

        lines.append("")
        values = data.get("values", [])
        if values:
            lines.append("Top values:")
            for v in values:
                val_str = str(v.get("value")) if v.get("value") is not None else "NULL"
                lines.append(f"  {val_str}: {v.get('count', 0):,}")
        else:
            lines.append("No values found.")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"
