"""Model verification tools: check_model_schema, analyze_grain, validate_model_output, etc."""

from __future__ import annotations

import re

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.helpers import _get_column_names
from gateway.mcp.server import mcp
from gateway.mcp.validation import _MODEL_NAME_RE, _quote_table, _validate_connection_name, _validate_sql


@audited_tool(mcp)
async def check_model_schema(connection_name: str, model_name: str, yml_columns: str) -> str:
    """
    Compare actual DuckDB table columns against an expected YML column list.

    Identifies missing columns, extra columns, and case mismatches between
    the materialized table and the schema defined in your dbt YML file.

    Args:
        connection_name: Name of a configured database connection
        model_name: Name of the dbt model / table to inspect
        yml_columns: Comma-separated list of column names from the YML schema

    Returns:
        Formatted schema comparison report, or an error message.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not yml_columns or not yml_columns.strip():
        return "Error: yml_columns cannot be empty."

    expected: list[str] = [c.strip() for c in yml_columns.split(",") if c.strip()]
    if not expected:
        return "Error: No column names found in yml_columns."

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

    try:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            actual = await _get_column_names(connector, conn_info.db_type, model_name)
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    if not actual:
        return f"Error: Model '{model_name}' not found in database. Has it been materialized yet?"

    expected_lower = {c.lower(): c for c in expected}
    actual_lower = {c.lower(): c for c in actual}

    matching = [c for c in expected if c in actual]
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    case_mismatches = [
        f"{expected_lower[k]} (expected) vs {actual_lower[k]} (actual)"
        for k in expected_lower
        if k in actual_lower and expected_lower[k] != actual_lower[k]
    ]

    def _fmt(items: list[str]) -> str:
        return ", ".join(items) if items else "(none)"

    lines = [
        f"Schema check for '{model_name}':",
        f"  Expected: {len(expected)} columns | Actual: {len(actual)} columns",
        f"  [OK] Matching: {_fmt(matching)}",
        f"  [X] Missing: {_fmt(missing)}",
        f"  [X] Extra: {_fmt(extra)}",
        f"  [!] Case mismatch: {_fmt(case_mismatches)}",
    ]
    return "\n".join(lines)


@audited_tool(mcp)
async def analyze_grain(connection_name: str, table_name: str, candidate_keys: str = "") -> str:
    """
    Analyze the cardinality and grain of a table.

    Helps agents understand if a model is fan-outing or has duplicates by
    checking row counts and distinctness of candidate key columns.

    Args:
        connection_name: Name of a configured database connection
        table_name: Name of the table to analyze
        candidate_keys: Optional comma-separated column names to test as grain keys

    Returns:
        Formatted grain analysis report, or an error message.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not table_name or not _MODEL_NAME_RE.match(table_name):
        return f"Error: Invalid table name '{table_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."

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

    try:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            count_rows = await connector.execute(f"SELECT COUNT(*) as total_rows FROM {_quote_table(table_name)}")
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    total_rows: int = count_rows[0].get("total_rows", 0) if count_rows else 0

    _SAFE_COL_RE = re.compile(r"^[a-zA-Z0-9_]{1,128}$")
    if candidate_keys:
        keys: list[str] = [k.strip() for k in candidate_keys.split(",") if k.strip()]
        invalid_keys = [k for k in keys if not _SAFE_COL_RE.match(k)]
        if invalid_keys:
            return f"Error: Invalid candidate key name(s): {', '.join(invalid_keys)}"
    else:
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                all_col_names = await _get_column_names(connector, conn_info.db_type, table_name)
        except Exception as e:
            return f"Error fetching schema: {sanitize_mcp_error(str(e))}"
        id_cols = [c for c in all_col_names if c.lower() == "id" or c.lower().endswith("_id")]
        keys = id_cols[:5]

    lines = [
        f"Grain analysis for '{table_name}':",
        f"  Total rows: {total_rows:,}",
        "  Candidate key check:",
    ]

    unique_keys: list[str] = []
    if keys:
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                for key in keys:
                    try:
                        safe_key = key.replace('"', '""')
                        dist_rows = await connector.execute(
                            f'SELECT COUNT(DISTINCT "{safe_key}") as distinct_count FROM {_quote_table(table_name)}'
                        )
                        distinct_count: int = dist_rows[0].get("distinct_count", 0) if dist_rows else 0
                        if distinct_count == total_rows:
                            lines.append(f"    {key}: {distinct_count:,} distinct (UNIQUE - this is likely the grain)")
                            unique_keys.append(key)
                        else:
                            fan_out = total_rows / distinct_count if distinct_count > 0 else 0
                            lines.append(
                                f"    {key}: {distinct_count:,} distinct (NOT unique - fan-out factor ~{fan_out:.1f}x)"
                            )
                    except Exception as e:
                        lines.append(f"    {key}: error checking distinctness ({sanitize_mcp_error(str(e), cap=100)})")
        except Exception as e:
            lines.append(f"    error opening connection: {sanitize_mcp_error(str(e), cap=100)}")

    if not keys:
        lines.append("    (no candidate keys found or provided)")

    if unique_keys:
        lines.append(f"  Recommendation: {unique_keys[0]} appears to be the grain key.")
    else:
        lines.append("  Recommendation: No unique key found among candidates. Consider adding a surrogate key.")

    return "\n".join(lines)


@audited_tool(mcp)
async def validate_model_output(
    connection_name: str,
    model_name: str,
    source_table: str = "",
    expected_row_count: int = 0,
) -> str:
    """
    Post-build row count validation for a dbt model.

    Detects fan-outs, empty models, and optional row count mismatches
    by comparing the model's row count against a source table or an
    expected value.

    Args:
        connection_name: Name of a configured database connection
        model_name: Name of the materialized dbt model to validate
        source_table: Optional upstream source table to compare row counts against
        expected_row_count: Optional expected row count (0 means skip check)

    Returns:
        Formatted validation report, or an error message.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."

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

    try:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            model_rows_result = await connector.execute(f"SELECT COUNT(*) as row_count FROM {_quote_table(model_name)}")
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    model_rows: int = model_rows_result[0].get("row_count", 0) if model_rows_result else 0

    source_rows: int | None = None
    source_error: str | None = None
    if source_table:
        if not _MODEL_NAME_RE.match(source_table):
            return f"Error: Invalid source_table name '{source_table}'."
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                src_result = await connector.execute(f"SELECT COUNT(*) as row_count FROM {_quote_table(source_table)}")
            source_rows = src_result[0].get("row_count", 0) if src_result else 0
        except Exception as e:
            source_error = sanitize_mcp_error(str(e))

    lines = [
        f"Model output validation: '{model_name}'",
        f"  Row count: {model_rows:,}",
    ]

    if model_rows == 0:
        lines.append("  WARNING: Model returned 0 rows.")

    if source_table:
        if source_error:
            lines.append(f"  Source '{source_table}': error fetching row count ({source_error})")
        elif source_rows is not None:
            lines.append(f"  Source '{source_table}': {source_rows:,} rows")
            if source_rows > 0:
                ratio = model_rows / source_rows
                if ratio < 0.5:
                    warning = "WARNING: Model has significantly fewer rows than source -- possible data loss or over-filtering."
                elif ratio > 2.0:
                    warning = "WARNING: Fan-out detected -- model has more rows than source. Check for unintended cross-joins."
                else:
                    warning = "OK - no fan-out detected"
                lines.append(f"  Fan-out ratio: {ratio:.2f}x ({warning})")
            else:
                lines.append("  Fan-out ratio: N/A (source has 0 rows)")

    if expected_row_count > 0:
        match_label = "MATCH" if model_rows == expected_row_count else "MISMATCH"
        lines.append(f"  Expected row count: {expected_row_count:,} - {match_label}")

    return "\n".join(lines)


@audited_tool(mcp)
async def audit_model_sources(
    connection_name: str,
    model_name: str,
    source_tables: str,
    sample_nulls: bool = True,
) -> str:
    """
    Single-call cardinality audit for a materialized dbt model and its sources.

    Queries all upstream source tables and the model itself, computes row count
    ratios (fan-out / over-filter detection), and optionally scans every output
    column for NULL fraction and constant-value patterns.

    Args:
        connection_name: Name of a configured database connection
        model_name: Name of the materialized dbt model to audit
        source_tables: Comma-separated list of upstream source/staging tables (1-10)
        sample_nulls: If True, run NULL-fraction and constant-value scan on output columns

    Returns:
        Formatted diagnostic report, or an error message.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not source_tables or not source_tables.strip():
        return "Error: source_tables cannot be empty. Provide at least one upstream table name."

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

    # Step 1: Get model row count.
    try:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            model_result = await connector.execute(f"SELECT COUNT(*) as row_count FROM {_quote_table(model_name)}")
    except Exception as e:
        return f"Error: could not query model '{model_name}': {sanitize_mcp_error(str(e))}"

    model_rows: int = model_result[0].get("row_count", 0) if model_result else 0

    # Step 2: Parse and validate source table names.
    raw_sources = [s.strip() for s in source_tables.split(",") if s.strip()]
    if len(raw_sources) > 10:
        raw_sources = raw_sources[:10]

    # Step 3: Query each source table, compute ratio, classify.
    source_lines: list[str] = []
    diagnosis_lines: list[str] = []

    for src in raw_sources:
        if not _MODEL_NAME_RE.match(src):
            source_lines.append(f"  {src}:  ERROR: invalid table name (skipped)")
            continue
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                src_result = await connector.execute(f"SELECT COUNT(*) as row_count FROM {_quote_table(src)}")
            src_rows: int = src_result[0].get("row_count", 0) if src_result else 0
        except Exception as e:
            source_lines.append(f"  {src}:  ERROR: {sanitize_mcp_error(str(e), cap=100)}")
            continue

        if src_rows == 0:
            ratio_str = "N/A"
            classification = "WARNING: source has 0 rows"
            diagnosis_lines.append(f"  - {src} has 0 rows: source table may be empty or not yet built")
        else:
            ratio = model_rows / src_rows
            ratio_str = f"{ratio:.2f}x"
            if ratio < 0.5:
                classification = (
                    "WARNING: OVER-FILTER — fewer model rows than source (check LEFT vs INNER JOIN or WHERE clause)"
                )
                diagnosis_lines.append(
                    f"  - {src} ratio {ratio_str}: check if INNER JOIN should be LEFT JOIN, or remove over-restrictive WHERE"
                )
            elif ratio > 2.0:
                classification = "WARNING: FAN-OUT — model has more rows than source (check for missing pre-aggregation or cross-join)"
                diagnosis_lines.append(
                    f"  - {src} ratio {ratio_str}: pre-aggregate or deduplicate {src} before joining; check join key uniqueness"
                )
            else:
                classification = "OK"

        label = src.ljust(20)
        source_lines.append(f"  {label} {src_rows:>10,} rows  → ratio {ratio_str:<8} {classification}")

    # Step 4: NULL-fraction and constant-value scan on output columns.
    col_scan_lines: list[str] = []
    col_scan_header = ""

    if sample_nulls and model_rows > 0:
        _SAFE_COL_RE = re.compile(r"^[a-zA-Z0-9_]{1,128}$")
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                all_cols = await _get_column_names(connector, conn_info.db_type, model_name)
            total_col_count = len(all_cols)
            cols = all_cols[:20]

            if total_col_count > 20:
                col_scan_header = f"Column scan (showing first 20 of {total_col_count} cols):"
            else:
                col_scan_header = f"Column scan ({len(cols)} cols):"

            for col in cols:
                if not _SAFE_COL_RE.match(col):
                    col_scan_lines.append(f"  [--] {col}: skipped (unsafe column name)")
                    continue
                try:
                    async with pool_manager.connection(
                        conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                    ) as connector:
                        col_result = await connector.execute(
                            f'SELECT COUNT(*) FILTER (WHERE "{col}" IS NULL) as nulls, '
                            f'COUNT(DISTINCT "{col}") as dist '
                            f"FROM {_quote_table(model_name)}"
                        )
                    null_count: int = col_result[0].get("nulls", 0) if col_result else 0
                    dist_count: int = col_result[0].get("dist", 0) if col_result else 0
                    null_frac = null_count / model_rows if model_rows > 0 else 0.0

                    col_label = col.ljust(24)
                    if dist_count == 1:
                        col_scan_lines.append(
                            f"  [!!] {col_label}  {dist_count:>8,} distinct — CONSTANT: all rows same value (check CASE WHEN literal or SELECT alias)"
                        )
                        diagnosis_lines.append(
                            f"  - {col} CONSTANT: verify CASE WHEN literals match source values (run SELECT DISTINCT on source col)"
                        )
                    elif null_frac > 0.5:
                        pct = null_frac * 100
                        col_scan_lines.append(
                            f"  [!!] {col_label}  {null_count:>8,} nulls ({pct:.1f}%) — LEFT JOIN may be dropping values; use COALESCE or fix join key"
                        )
                        diagnosis_lines.append(
                            f"  - {col} {pct:.0f}% null: verify join key is correct; consider COALESCE({col}, 0) if nulls are valid zeros"
                        )
                    else:
                        col_scan_lines.append(f"  [OK]  {col_label}  {dist_count:>8,} distinct, {null_count:,} nulls")
                except Exception as e:
                    col_scan_lines.append(f"  [--] {col}: error ({sanitize_mcp_error(str(e), cap=100)})")

        except Exception:
            col_scan_header = "Column scan: unavailable (column introspection failed)"

    elif sample_nulls and model_rows == 0:
        col_scan_header = "Column scan: skipped (model has 0 rows)"

    # Step 5: Assemble report.
    report_lines: list[str] = [
        f"Source audit for model '{model_name}' ({model_rows:,} rows):",
        "",
        "Sources:",
    ]
    report_lines.extend(source_lines)

    if col_scan_header:
        report_lines.append("")
        report_lines.append(col_scan_header)
        report_lines.extend(col_scan_lines)

    if diagnosis_lines:
        report_lines.append("")
        report_lines.append("Diagnosis:")
        report_lines.extend(diagnosis_lines)

    return "\n".join(report_lines)


@audited_tool(mcp)
async def compare_join_types(
    connection_name: str,
    left_table: str,
    right_table: str,
    join_keys: str,
    where_clause: str = "",
) -> str:
    """
    Compare row counts across different JOIN types between two tables.

    Shows what INNER JOIN, LEFT JOIN, RIGHT JOIN, and FULL OUTER JOIN would produce,
    helping you choose the correct JOIN type for your model. Also shows how many
    rows from each side have no match in the other table.

    Args:
        connection_name: Name of a configured database connection
        left_table: Left table name (can be schema.table or just table)
        right_table: Right table name (can be schema.table or just table)
        join_keys: Comma-separated join key pairs, e.g. "a.id = b.id, a.date = b.date"
        where_clause: Optional WHERE clause (without the WHERE keyword)

    Returns:
        Formatted report showing row counts for each JOIN type and match analysis.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not left_table or not _MODEL_NAME_RE.match(left_table):
        return f"Error: Invalid left_table name '{left_table}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not right_table or not _MODEL_NAME_RE.match(right_table):
        return f"Error: Invalid right_table name '{right_table}'. Use only letters, numbers, underscores, dots (1-256 chars)."
    if not join_keys or not join_keys.strip():
        return 'Error: join_keys cannot be empty. Provide at least one join key pair, e.g. "a.id = b.id".'
    if err := _validate_sql(join_keys):
        return f"Error: {err}"
    if where_clause and where_clause.strip():
        if err := _validate_sql(where_clause):
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

    from gateway.connectors.pool_manager import pool_manager

    # Extract left and right columns from the first join key for NULL detection.
    # join_keys like "a.id = b.id" — extract "a.id" and "b.id"
    first_key = join_keys.split(",")[0].strip()
    parts = first_key.split("=")
    if len(parts) != 2:
        return "Error: join_keys must be in format 'a.col = b.col'. Could not parse left/right columns."
    left_col = parts[0].strip()
    right_col = parts[1].strip()

    where_part = f"WHERE {where_clause}" if where_clause and where_clause.strip() else ""

    _qt_left = _quote_table(left_table)
    _qt_right = _quote_table(right_table)

    sql = f"""
WITH
left_count AS (SELECT COUNT(*) AS cnt FROM {_qt_left}),
right_count AS (SELECT COUNT(*) AS cnt FROM {_qt_right}),
inner_join AS (
    SELECT COUNT(*) AS cnt
    FROM {_qt_left} a
    INNER JOIN {_qt_right} b ON {join_keys}
    {where_part}
),
left_join AS (
    SELECT COUNT(*) AS cnt,
           COUNT({right_col}) AS matched,
           COUNT(*) - COUNT({right_col}) AS unmatched
    FROM {_qt_left} a
    LEFT JOIN {_qt_right} b ON {join_keys}
    {where_part}
),
right_join AS (
    SELECT COUNT(*) AS cnt,
           COUNT({left_col}) AS matched,
           COUNT(*) - COUNT({left_col}) AS unmatched
    FROM {_qt_left} a
    RIGHT JOIN {_qt_right} b ON {join_keys}
    {where_part}
),
full_join AS (
    SELECT COUNT(*) AS cnt
    FROM {_qt_left} a
    FULL OUTER JOIN {_qt_right} b ON {join_keys}
    {where_part}
)
SELECT
    (SELECT cnt FROM left_count) AS left_rows,
    (SELECT cnt FROM right_count) AS right_rows,
    (SELECT cnt FROM inner_join) AS inner_rows,
    (SELECT cnt FROM left_join) AS left_join_rows,
    (SELECT matched FROM left_join) AS left_matched,
    (SELECT unmatched FROM left_join) AS left_unmatched,
    (SELECT cnt FROM right_join) AS right_join_rows,
    (SELECT matched FROM right_join) AS right_matched,
    (SELECT unmatched FROM right_join) AS right_unmatched,
    (SELECT cnt FROM full_join) AS full_join_rows
"""

    try:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            result = await connector.execute(sql)
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    if not result:
        return "Error: Query returned no results."

    row = result[0]
    left_rows: int = row.get("left_rows", 0)
    right_rows: int = row.get("right_rows", 0)
    inner_rows: int = row.get("inner_rows", 0)
    left_join_rows: int = row.get("left_join_rows", 0)
    left_unmatched: int = row.get("left_unmatched", 0)
    right_join_rows: int = row.get("right_join_rows", 0)
    right_unmatched: int = row.get("right_unmatched", 0)
    full_join_rows: int = row.get("full_join_rows", 0)

    lines = [
        f"JOIN Impact Analysis: {left_table} × {right_table}",
        f"  ON {join_keys}",
        "",
        "Source Tables:",
        f"  {left_table}: {left_rows:,} rows",
        f"  {right_table}: {right_rows:,} rows",
        "",
        "JOIN Results:",
        f"  INNER JOIN:      {inner_rows:,} rows",
        f"  LEFT JOIN:       {left_join_rows:,} rows  ({left_unmatched:,} left rows have no match)",
        f"  RIGHT JOIN:      {right_join_rows:,} rows  ({right_unmatched:,} right rows have no match)",
        f"  FULL OUTER JOIN: {full_join_rows:,} rows",
    ]

    if inner_rows < left_join_rows:
        lines.append("")
        lines.append(
            f"⚠ INNER JOIN drops {left_join_rows - inner_rows:,} rows from {left_table} that have no match in {right_table}."
        )
        lines.append(f"  Use LEFT JOIN to preserve all {left_table} rows.")

    if inner_rows > left_rows or inner_rows > right_rows:
        lines.append("")
        lines.append(
            f"⚠ FAN-OUT detected: INNER JOIN ({inner_rows:,}) > source rows. Join keys are not unique — duplicates in one table multiply rows in the other."
        )

    if left_join_rows == inner_rows:
        lines.append("")
        lines.append(f"✓ All {left_table} rows match — LEFT JOIN and INNER JOIN produce the same result.")

    return "\n".join(lines)
