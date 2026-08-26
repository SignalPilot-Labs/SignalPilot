"""Model verification tools: check_model_schema, analyze_grain, validate_model_output, etc."""

import re

from gateway.engine import inject_limit, sqlglot_dialect
from gateway.engine import validate_sql as engine_validate_sql
from gateway.engine._sqlglot import exp, sqlglot
from gateway.engine.denylists import _check_dangerous_functions
from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.helpers import _get_column_names
from gateway.mcp.server import mcp
from gateway.mcp.validation import _MODEL_NAME_RE, _quote_table, _validate_connection_name, _validate_sql
from gateway.verification import compare_columns


def _qid(name: str) -> str:
    """Quote a SQL identifier with double-quote doubling."""
    return '"' + name.replace('"', '""') + '"'


# Strict grammar for one join key pair: qualified column = qualified column.
# No functions, subqueries, comments, or operators other than a single '='.
_JOIN_KEY_PAIR_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]{0,127})\.([A-Za-z_][A-Za-z0-9_]{0,127})"
    r"\s*=\s*"
    r"([A-Za-z_][A-Za-z0-9_]{0,127})\.([A-Za-z_][A-Za-z0-9_]{0,127})$"
)


def _parse_join_keys(join_keys: str) -> tuple[list[tuple[str, str]], str | None]:
    """Parse comma-separated join key pairs into (left_col, right_col) tuples.

    Returns (pairs, None) on success or ([], error_message) on rejection.
    """
    pairs: list[tuple[str, str]] = []
    for raw in join_keys.split(","):
        pair = raw.strip()
        m = _JOIN_KEY_PAIR_RE.match(pair)
        if not m:
            return [], (
                f"Invalid join key pair '{pair}'. "
                'Each pair must be a qualified-column equality like "a.id = b.id" '
                "(letters, numbers, underscores only)."
            )
        lq, lc, rq, rc = m.groups()
        pairs.append((f"{lq}.{lc}", f"{rq}.{rc}"))
    return pairs, None


def _validate_where_predicate(where_clause: str, dialect: str) -> str | None:
    """Validate where_clause as a single boolean predicate expression.

    Rejects statements, stacked statements, subqueries, comments, and
    dangerous functions. Returns an error message or None if valid.
    """
    if ";" in where_clause or "--" in where_clause or "/*" in where_clause:
        return "where_clause must be a plain predicate — semicolons and comments are not allowed."
    try:
        predicate = sqlglot.parse_one(where_clause, dialect=dialect, into=exp.Condition)
    except Exception as e:
        return f"Could not parse where_clause as a boolean predicate: {str(e)[:100]}"
    if predicate is None:
        return "Could not parse where_clause as a boolean predicate."
    if predicate.find(exp.Select, exp.Subquery, exp.Exists):
        return "Subqueries are not allowed in where_clause."
    if reason := _check_dangerous_functions(predicate, dialect):
        return reason
    return None


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

    comparison = compare_columns(expected, actual)

    def _fmt(items: list[str]) -> str:
        return ", ".join(items) if items else "(none)"

    lines = [
        f"Schema check for '{model_name}':",
        f"  Expected: {len(expected)} columns | Actual: {len(actual)} columns",
        f"  [OK] Matching: {_fmt(comparison.matching)}",
        f"  [X] Missing: {_fmt(comparison.missing)}",
        f"  [X] Extra: {_fmt(comparison.extra)}",
        f"  [!] Case mismatch: {_fmt(comparison.case_mismatches)}",
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
    """Report model/source row ratios and output-column profiles.

    Queries the supplied upstream relations and model, then reports row counts,
    ratios, NULL fractions, and distinct-value profiles as observations.
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
            classification = "OBSERVATION: source has 0 rows"
        else:
            ratio = model_rows / src_rows
            ratio_str = f"{ratio:.2f}x"
            if ratio < 0.5:
                classification = "OBSERVATION: model/source ratio below 0.5"
            elif ratio > 2.0:
                classification = "OBSERVATION: model/source ratio above 2.0"
            else:
                classification = "OBSERVATION"

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
                            f"  [OBS] {col_label}  {dist_count:>8,} distinct, {null_count:,} nulls"
                        )
                    elif null_frac > 0.5:
                        pct = null_frac * 100
                        col_scan_lines.append(
                            f"  [OBS] {col_label}  {dist_count:>8,} distinct, {null_count:>8,} nulls ({pct:.1f}%)"
                        )
                    else:
                        col_scan_lines.append(f"  [OBS] {col_label}  {dist_count:>8,} distinct, {null_count:,} nulls")
                except Exception as e:
                    col_scan_lines.append(f"  [--] {col}: error ({sanitize_mcp_error(str(e), cap=100)})")

        except Exception:
            col_scan_header = "Column scan: unavailable (column introspection failed)"

    elif sample_nulls and model_rows == 0:
        col_scan_header = "Column scan: skipped (model has 0 rows)"

    # Step 5: Sample rows (first 5).
    sample_lines: list[str] = []
    if model_rows > 0:
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                sample_result = await connector.execute(
                    f"SELECT * FROM {_quote_table(model_name)} LIMIT 5"
                )
            if sample_result:
                cols = list(sample_result[0].keys())
                sample_lines.append(f"Sample rows (5 of {model_rows:,}):")
                sample_lines.append(f"  Columns: {', '.join(cols[:15])}{'...' if len(cols) > 15 else ''}")
                for row in sample_result[:5]:
                    vals = [str(v)[:30] for v in row.values()]
                    sample_lines.append(f"  {' | '.join(vals[:10])}")
        except Exception:
            sample_lines.append("Sample rows: unavailable")

    # Step 6: Low-cardinality column values + grain duplicate check.
    value_lines: list[str] = []
    if sample_nulls and model_rows > 0:
        try:
            async with pool_manager.connection(
                conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
            ) as connector:
                all_cols = await _get_column_names(connector, conn_info.db_type, model_name)

            # Show actual distinct values for columns with <= 15 distinct values
            _SAFE_COL_RE = re.compile(r"^[a-zA-Z0-9_]{1,128}$")
            low_card_cols = []
            for line in col_scan_lines:
                # Parse "  [OBS] col_name   N distinct, M nulls"
                if "distinct" in line and "[OBS]" in line:
                    parts = line.split()
                    col_idx = 1
                    col_name = parts[col_idx] if col_idx < len(parts) else ""
                    dist_idx = next((i for i, p in enumerate(parts) if p == "distinct"), -1)
                    if dist_idx > 0:
                        try:
                            dist_val = int(parts[dist_idx - 1].replace(",", ""))
                            if 2 <= dist_val <= 15 and _SAFE_COL_RE.match(col_name):
                                low_card_cols.append(col_name)
                        except (ValueError, IndexError):
                            pass

            if low_card_cols:
                value_lines.append("Low-cardinality column values:")
                for col in low_card_cols[:8]:
                    try:
                        async with pool_manager.connection(
                            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                        ) as connector:
                            val_result = await connector.execute(
                                f'SELECT DISTINCT "{col}" as val FROM {_quote_table(model_name)} ORDER BY 1 LIMIT 15'
                            )
                        vals = [str(r["val"]) for r in val_result] if val_result else []
                        value_lines.append(f"  {col}: [{', '.join(vals)}]")
                    except Exception:
                        pass

            # Grain duplicate check: find first unique-looking column
            grain_col = None
            for col in all_cols[:5]:
                for line in col_scan_lines:
                    if col in line and "distinct" in line:
                        try:
                            parts = line.split()
                            dist_idx = next((i for i, p in enumerate(parts) if p == "distinct"), -1)
                            if dist_idx > 0:
                                dist_val = int(parts[dist_idx - 1].replace(",", ""))
                                if dist_val == model_rows:
                                    grain_col = col
                                    break
                        except (ValueError, IndexError):
                            pass
                if grain_col:
                    break

            if grain_col:
                value_lines.append(f"Grain key: {grain_col} ({model_rows} distinct = row count — unique)")
            else:
                value_lines.append("Grain key: no single column is unique (composite key or fan-out)")

        except Exception:
            pass

    # Step 7: Assemble report.
    report_lines: list[str] = [
        f"Source audit for model '{model_name}' ({model_rows:,} rows):",
        "",
        "Sources:",
    ]
    report_lines.extend(source_lines)

    if sample_lines:
        report_lines.append("")
        report_lines.extend(sample_lines)

    if col_scan_header:
        report_lines.append("")
        report_lines.append(col_scan_header)
        report_lines.extend(col_scan_lines)

    if value_lines:
        report_lines.append("")
        report_lines.extend(value_lines)

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
        where_clause: Optional filter (without the WHERE keyword). A predicate that
            references only one side's alias (a. for left, b. for right) is applied
            to that table BEFORE the join, so outer-join match counts stay truthful.
            A predicate referencing both sides (or no alias) is applied AFTER the
            join and removes unmatched outer-join rows - the report says so when
            that happens.

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
    join_pairs, err = _parse_join_keys(join_keys)
    if err:
        return f"Error: {err}"
    if where_clause and where_clause.strip():
        if err := _validate_sql(where_clause):
            return f"Error: {err}"

    from gateway.governance.annotations import load_annotations
    from gateway.governance.context import require_org_id

    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"

        extras = await store.get_credential_extras(connection_name)

        annotations = load_annotations(require_org_id(), connection_name)
        blocked_tables = annotations.blocked_tables

    from gateway.connectors.pool_manager import pool_manager

    dialect = sqlglot_dialect(conn_info.db_type)

    if where_clause and where_clause.strip():
        if err := _validate_where_predicate(where_clause.strip(), dialect):
            return f"Error: {err}"

    # First join key's sides are used for NULL-based match detection.
    left_col, right_col = join_pairs[0]
    join_condition = " AND ".join(f"{lhs} = {rhs}" for lhs, rhs in join_pairs)

    _qt_left = _quote_table(left_table)
    _qt_right = _quote_table(right_table)

    # Push a single-side predicate into that side BEFORE the join. A post-join
    # WHERE on the right alias silently deletes a LEFT JOIN's unmatched rows and
    # makes LEFT and INNER look identical, which misleads the join-type choice.
    left_from = f"{_qt_left} a"
    right_from = f"{_qt_right} b"
    where_part = ""
    filter_note = ""
    pred = where_clause.strip() if where_clause else ""
    if pred:
        refs_left = bool(re.search(r"\ba\s*\.", pred))
        refs_right = bool(re.search(r"\bb\s*\.", pred))
        if refs_right and not refs_left:
            right_from = f"(SELECT * FROM {_qt_right} b WHERE {pred}) b"
            filter_note = f"Filter applied to {right_table} BEFORE the join: {pred}"
        elif refs_left and not refs_right:
            left_from = f"(SELECT * FROM {_qt_left} a WHERE {pred}) a"
            filter_note = f"Filter applied to {left_table} BEFORE the join: {pred}"
        else:
            where_part = f"WHERE {pred}"
            filter_note = (
                "NOTE: where_clause references both sides or no alias, so it is applied AFTER the join - "
                "unmatched outer-join rows that fail it are removed from these counts. "
                "Pass a predicate on a single alias (a. or b.) to pre-filter that side instead."
            )

    sql = f"""
WITH
left_count AS (SELECT COUNT(*) AS cnt FROM {left_from}),
right_count AS (SELECT COUNT(*) AS cnt FROM {right_from}),
inner_join AS (
    SELECT COUNT(*) AS cnt
    FROM {left_from}
    INNER JOIN {right_from} ON {join_condition}
    {where_part}
),
left_join AS (
    SELECT COUNT(*) AS cnt,
           COUNT({right_col}) AS matched,
           COUNT(*) - COUNT({right_col}) AS unmatched
    FROM {left_from}
    LEFT JOIN {right_from} ON {join_condition}
    {where_part}
),
right_join AS (
    SELECT COUNT(*) AS cnt,
           COUNT({left_col}) AS matched,
           COUNT(*) - COUNT({left_col}) AS unmatched
    FROM {left_from}
    RIGHT JOIN {right_from} ON {join_condition}
    {where_part}
),
full_join AS (
    SELECT COUNT(*) AS cnt
    FROM {left_from}
    FULL OUTER JOIN {right_from} ON {join_condition}
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

    validation = engine_validate_sql(sql, blocked_tables=blocked_tables or None, dialect=dialect)
    if not validation.ok:
        return f"Error: Query blocked: {validation.blocked_reason}"

    try:
        safe_sql = inject_limit(sql, 1000, dialect=dialect)
    except ValueError as exc:
        return f"Error: Query blocked: {exc}"

    try:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            result = await connector.execute(safe_sql)
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
        f"  ON {join_condition}",
        "",
        "Source Tables (after any pre-join filter):",
        f"  {left_table}: {left_rows:,} rows",
        f"  {right_table}: {right_rows:,} rows",
    ]
    if filter_note:
        lines.append(f"  {filter_note}")
    lines += [
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
            f"{left_join_rows - inner_rows:,} rows from {left_table} have no match in {right_table} - "
            "confirm from the task, YML, or sibling models whether the contract preserves or excludes them."
        )

    if inner_rows > left_rows:
        lines.append("")
        lines.append(
            f"FAN-OUT: INNER JOIN ({inner_rows:,}) > {left_table} rows ({left_rows:,}) - the right-side join key is not unique, so matches multiply driving rows."
        )

    if left_join_rows == inner_rows:
        lines.append("")
        lines.append(f"✓ All {left_table} rows match — LEFT JOIN and INNER JOIN produce the same result.")

    return "\n".join(lines)


@audited_tool(mcp)
async def verify_model_values(connection_name: str, model_name: str) -> str:
    """
    Cross-validate a model's aggregate metric values against raw source data.

    Queries the model output, identifies numeric (metric) columns and the
    largest dimension slice, then independently runs COUNT(*) and
    COUNT(DISTINCT <key>) on each upstream table for that slice.
    Reports any discrepancy between the model's values and the raw source.

    Use this AFTER building a model to catch wrong aggregation functions
    (e.g. COUNT(DISTINCT id) when COUNT(*) is correct).

    Args:
        connection_name: Name of a configured database connection
        model_name: Name of the dbt model / table to verify

    Returns:
        Formatted value verification report showing model values vs source baselines.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'."

    try:
        async with _store_session() as store:
            conn = await store.get_connection(connection_name)
            if not conn:
                return f"Error: Connection '{connection_name}' not found."

            from gateway.connectors.pool_manager import pool_manager

            conn_str = await store.get_connection_string(connection_name)
            if not conn_str:
                return "Error: No credentials for this connection."
            extras = await store.get_credential_extras(connection_name)

            async def _query(sql: str) -> list:
                async with pool_manager.connection(
                    conn.db_type, conn_str, credential_extras=extras, connection_name=connection_name
                ) as connector:
                    return await connector.execute(sql)

            async def _query_one(sql: str):
                rows = await _query(sql)
                return rows[0] if rows else None

            # Get model columns
            safe_model = model_name.replace("'", "''")
            col_rows = await _query(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_name = '{safe_model}' ORDER BY ordinal_position"
            )
            if not col_rows:
                return f"Error: Table '{model_name}' not found or has no columns."

            columns = [(r["column_name"], r["data_type"]) for r in col_rows]
            numeric_types = ("INTEGER", "BIGINT", "DOUBLE", "FLOAT", "DECIMAL", "NUMERIC", "HUGEINT", "INT")
            dim_types = ("VARCHAR", "TEXT", "DATE")

            metric_cols = [(n, t) for n, t in columns if any(k in t.upper() for k in numeric_types)]
            dim_cols = [(n, t) for n, t in columns if any(k in t.upper() for k in dim_types)]

            if not metric_cols:
                return f"No numeric columns in '{model_name}' — nothing to verify."

            # Get top row by first metric
            first_metric = metric_cols[0][0]
            top = await _query_one(
                f'SELECT * FROM {_quote_table(model_name)} ORDER BY {_qid(first_metric)} DESC LIMIT 1'
            )
            if not top:
                return f"No rows in '{model_name}'."

            # Find slice dimension
            slice_col = None
            slice_val = None
            for name, _ in dim_cols:
                if top.get(name) is not None:
                    slice_col = name
                    slice_val = top[name]
                    break

            # Find all tables in DB as potential upstreams
            all_tables_rows = await _query("SHOW TABLES")
            all_tables = [r[list(r.keys())[0]] for r in all_tables_rows]

            # Collect row counts and columns for candidate upstream tables.
            # Small warehouses: exhaustive per-table scan. Large warehouses:
            # per-table COUNT(*) over thousands of tables takes tens of
            # minutes, so fetch all columns in one catalog query, shortlist
            # by column overlap with the model, and only COUNT the shortlist.
            table_info: list[tuple[str, int, list[str]]] = []  # (name, row_count, columns)
            scan_tables = [t for t in all_tables if t != model_name]
            if len(scan_tables) > 50:
                cols_by_table: dict[str, list[str]] = {}
                try:
                    all_col_rows = await _query(
                        "SELECT table_name, column_name FROM information_schema.columns"
                    )
                    for r in all_col_rows:
                        cols_by_table.setdefault(r["table_name"], []).append(r["column_name"])
                except Exception:
                    cols_by_table = {}
                model_col_set = {n.lower() for n, _ in columns}

                def _overlap(tbl: str) -> int:
                    return sum(
                        1 for c in cols_by_table.get(tbl, []) if c.lower() in model_col_set
                    )

                pool = [t for t in scan_tables if _overlap(t) > 0]
                pool.sort(key=_overlap, reverse=True)
                scan_tables = pool[:15] if pool else scan_tables[:15]
            for tbl in scan_tables:
                try:
                    row = await _query_one(f'SELECT COUNT(*) AS cnt FROM {_quote_table(tbl)}')
                    cnt = row["cnt"] if row else 0
                    safe_tbl = tbl.replace("'", "''")
                    tbl_col_rows = await _query(
                        f"SELECT column_name FROM information_schema.columns "
                        f"WHERE table_name = '{safe_tbl}'"
                    )
                    tbl_cols = [r["column_name"] for r in tbl_col_rows]
                    table_info.append((tbl, cnt, tbl_cols))
                except Exception:
                    pass

            if not table_info:
                return "No upstream tables found."

            # Pick top 3 candidates by row count (larger tables are more likely upstreams)
            table_info.sort(key=lambda x: x[1], reverse=True)
            candidates = table_info[:3]

            # Helper: build a slice filter for a candidate table
            def _build_slice(cand_name: str, cand_cols: list[str]) -> tuple[str, str]:
                """Returns (slice_sql, alias_prefix). Empty string if no filter possible."""
                if not slice_col or not slice_val:
                    return "", ""
                safe_val = str(slice_val).replace("'", "''")
                # Direct match: candidate has the slice column
                cand_col_match = next((c for c in cand_cols if c.lower() == slice_col.lower()), None)
                if cand_col_match:
                    return f"WHERE {_qid(cand_col_match)} = '{safe_val}'", ""
                # Indirect: find a dimension table with the slice column, join via shared key
                for dim_name, _, dim_cols in table_info:
                    if dim_name in (model_name, cand_name):
                        continue
                    dim_match = next((c for c in dim_cols if c.lower() == slice_col.lower()), None)
                    if not dim_match:
                        continue
                    # Find shared join key between candidate and dimension
                    cand_lower = {c.lower(): c for c in cand_cols}
                    dim_lower = {c.lower(): c for c in dim_cols}
                    shared_keys = [
                        (cand_lower[k], dim_lower[k])
                        for k in cand_lower
                        if k in dim_lower and k != slice_col.lower()
                    ]
                    if shared_keys:
                        cand_key, dim_key = shared_keys[0]
                        return (
                            f'INNER JOIN {_quote_table(dim_name)} _dim '
                            f'ON _cand.{_qid(cand_key)} = _dim.{_qid(dim_key)} '
                            f"WHERE _dim.{_qid(dim_match)} = '{safe_val}'",
                            "_cand",
                        )
                return "", ""

            lines = [
                f"## Value Verification: {model_name}",
                f"Top row slice: {slice_col} = '{slice_val}'" if slice_col else "No dimension for slicing",
                "",
            ]

            for metric_name, _ in metric_cols:
                model_val = top.get(metric_name)
                if model_val is None:
                    continue

                lines.append(f"### Metric: {metric_name}")
                lines.append(f"  Model value: {model_val}")
                lines.append("")

                any_candidate = False
                for cand_name, cand_rows, cand_cols in candidates:
                    cand_slice, cand_prefix = _build_slice(cand_name, cand_cols)
                    if not cand_slice:
                        lines.append(f"  Candidate: {cand_name} ({cand_rows:,} rows) — slice filter unavailable, skipped")
                        continue

                    any_candidate = True
                    lines.append(f"  Candidate: {cand_name} ({cand_rows:,} rows)")

                    # COUNT(*)
                    try:
                        if cand_prefix:
                            q = f'SELECT COUNT(*) AS cnt FROM {_quote_table(cand_name)} _cand {cand_slice}'
                        else:
                            q = f'SELECT COUNT(*) AS cnt FROM {_quote_table(cand_name)} {cand_slice}'
                        row = await _query_one(q)
                        count_star = row["cnt"] if row else None
                    except Exception:
                        count_star = None

                    if count_star is not None:
                        lines.append(f"    COUNT(*): {count_star}")

                    # COUNT(DISTINCT) for _id-like columns
                    id_cols = [c for c in cand_cols if c.lower().endswith("_id") or c.lower() == "id"][:3]
                    for key in id_cols:
                        try:
                            if cand_prefix:
                                q = f'SELECT COUNT(DISTINCT _cand.{_qid(key)}) AS cnt FROM {_quote_table(cand_name)} _cand {cand_slice}'
                            else:
                                q = f'SELECT COUNT(DISTINCT {_qid(key)}) AS cnt FROM {_quote_table(cand_name)} {cand_slice}'
                            row = await _query_one(q)
                            if row:
                                lines.append(f"    COUNT(DISTINCT {key}): {row['cnt']}")
                        except Exception:
                            pass

                    # Annotate match/mismatch
                    if count_star is not None and model_val:
                        try:
                            mv = float(model_val)
                            cs = float(count_star)
                            if mv > 0 and cs > 0:
                                ratio = cs / mv
                                if 0.9 <= ratio <= 1.1:
                                    lines.append("    → Model matches COUNT(*)")
                                else:
                                    lines.append(f"    → MISMATCH vs COUNT(*) ({ratio:.1f}x)")
                        except (ValueError, ZeroDivisionError):
                            pass

                    lines.append("")

                if not any_candidate:
                    lines.append("  (no candidate tables with valid slice filter)")
                    lines.append("")

            return "\n".join(lines)

    except Exception as exc:
        return sanitize_mcp_error(f"verify_model_values: {exc}")
