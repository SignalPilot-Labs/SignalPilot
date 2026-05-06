"""generate_model_blueprint — single-call research for building a dbt model.

Combines YML contract extraction, upstream cardinality analysis, sibling SQL
pattern reading, and status/flag column discovery into one deterministic output.
Replaces the non-deterministic researcher subagent with a reproducible tool call.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.helpers import _get_column_names
from gateway.mcp.server import mcp
from gateway.mcp.validation import _MODEL_NAME_RE, _quote_table, _validate_connection_name


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

_SAFE_DIR_RE = re.compile(r"^[a-zA-Z0-9_./ -]+$")
_STATUS_COL_PATTERNS = {
    "status", "type", "flag", "return_flag", "item_status", "order_status",
    "refund_status", "transaction_type", "line_status", "state",
    "payment_status", "charge_status", "subscription_status",
    "returnflag", "l_returnflag", "linestatus", "l_linestatus",
    "o_orderstatus", "orderstatus",
}


def _is_likely_key_column(col_name: str) -> bool:
    """Check if a column is likely a key/ID column (broader than just _id suffix)."""
    low = col_name.lower()
    if low == "id" or low.endswith("_id"):
        return True
    # TPC-H style: l_orderkey, o_custkey, ps_partkey, etc.
    if low.endswith("key"):
        return True
    # Common patterns: order_no, invoice_no, customer_no
    if low.endswith("_no") or low.endswith("_num") or low.endswith("_number"):
        return True
    return False


def _find_yml_contract(project_dir: Path, model_name: str) -> dict:
    """Parse YML files to find a model's column contract.

    Returns: {
        "description": str,
        "columns": [{"name": str, "description": str, "tests": list}],
        "refs": [str],
        "sources": [str],
    }
    """
    import yaml

    result: dict = {"description": "", "columns": [], "refs": [], "sources": []}
    models_dir = project_dir / "models"
    if not models_dir.exists():
        return result

    for yml_path in models_dir.rglob("*.yml"):
        if "dbt_packages" in str(yml_path):
            continue
        try:
            with open(yml_path) as f:
                data = yaml.safe_load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        for model in data.get("models", []):
            if model.get("name") != model_name:
                continue
            result["description"] = model.get("description", "")
            for col in model.get("columns", []):
                col_entry = {
                    "name": col.get("name", ""),
                    "description": col.get("description", ""),
                    "tests": [
                        t if isinstance(t, str) else list(t.keys())[0]
                        for t in col.get("tests", [])
                    ],
                }
                result["columns"].append(col_entry)
            # Extract refs from YML (for missing models with no SQL file)
            for ref_entry in model.get("refs", []):
                ref_name = ref_entry.get("name", "") if isinstance(ref_entry, dict) else str(ref_entry)
                if ref_name and ref_name not in result["refs"]:
                    result["refs"].append(ref_name)
            # Extract sources from YML
            for src_entry in model.get("sources", []):
                src_name = src_entry.get("name", "") if isinstance(src_entry, dict) else ""
                for tbl_entry in (src_entry.get("tables", []) if isinstance(src_entry, dict) else []):
                    tbl_name = tbl_entry.get("name", "") if isinstance(tbl_entry, dict) else str(tbl_entry)
                    if src_name and tbl_name:
                        result["sources"].append((src_name, tbl_name))
            break

    # Extract refs and sources from the model SQL if it exists (supplements YML)
    sql_path = _find_model_sql(project_dir, model_name)
    if sql_path and sql_path.exists():
        sql_text = sql_path.read_text()
        result["refs"] = re.findall(r"{{\s*ref\(['\"](\w+)['\"]\)\s*}}", sql_text)
        result["sources"] = re.findall(
            r"{{\s*source\(['\"](\w+)['\"],\s*['\"](\w+)['\"]\)\s*}}", sql_text
        )

    return result


def _find_model_sql(project_dir: Path, model_name: str) -> Path | None:
    """Find the SQL file for a model by name."""
    models_dir = project_dir / "models"
    if not models_dir.exists():
        return None
    for sql_path in models_dir.rglob(f"{model_name}.sql"):
        if "dbt_packages" not in str(sql_path):
            return sql_path
    return None


def _read_sibling_sql(project_dir: Path, model_name: str, max_siblings: int = 3) -> list[dict]:
    """Read complete SQL files in the same directory as the target model.

    Returns: [{"name": str, "sql": str}]
    """
    sql_path = _find_model_sql(project_dir, model_name)
    if not sql_path:
        return []

    siblings = []
    for sib_path in sql_path.parent.glob("*.sql"):
        if sib_path.stem == model_name:
            continue
        if "dbt_packages" in str(sib_path):
            continue
        try:
            sql_text = sib_path.read_text()
            # Skip stubs (very short files with only config + comments)
            stripped = re.sub(r"--.*$", "", sql_text, flags=re.MULTILINE).strip()
            stripped = re.sub(r"\{\{.*?\}\}", "", stripped).strip()
            if len(stripped) < 20:
                continue
            siblings.append({"name": sib_path.stem, "sql": sql_text[:2000]})
        except Exception:
            continue
        if len(siblings) >= max_siblings:
            break

    return siblings


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def _query_cardinalities(
    query_fn, table_name: str, columns: list[str]
) -> dict:
    """Query COUNT(*) and COUNT(DISTINCT) for key columns of a table."""
    result: dict = {"table": table_name, "total_rows": 0, "key_counts": {}}
    try:
        row = await query_fn(f"SELECT COUNT(*) AS cnt FROM {_quote_table(table_name)}")
        result["total_rows"] = row[0]["cnt"] if row else 0
    except Exception:
        return result

    id_cols = [c for c in columns if _is_likely_key_column(c)][:4]
    for col in id_cols:
        try:
            safe_col = col.replace('"', '""')
            row = await query_fn(
                f'SELECT COUNT(DISTINCT "{safe_col}") AS cnt FROM {_quote_table(table_name)}'
            )
            if row:
                result["key_counts"][col] = row[0]["cnt"]
        except Exception:
            pass

    return result


async def _discover_status_columns(
    query_fn, table_name: str, columns: list[str]
) -> list[dict]:
    """Find status/flag/type columns and their distinct values."""
    discoveries = []
    for col in columns:
        if col.lower() not in _STATUS_COL_PATTERNS:
            continue
        try:
            safe_col = col.replace('"', '""')
            rows = await query_fn(
                f'SELECT DISTINCT "{safe_col}" AS val FROM {_quote_table(table_name)} '
                f'ORDER BY 1 LIMIT 20'
            )
            values = [r["val"] for r in rows] if rows else []
            discoveries.append({"column": col, "table": table_name, "values": values})
        except Exception:
            pass
    return discoveries


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

@audited_tool(mcp)
async def generate_model_blueprint(
    connection_name: str,
    model_name: str,
    project_dir: str,
) -> str:
    """Generate a complete build plan for a dbt model in one call.

    Combines YML contract extraction, upstream cardinality analysis, sibling
    SQL pattern reading, and status/flag column discovery. Returns a
    deterministic, structured brief that replaces the researcher subagent.

    Args:
        connection_name: Name of a configured database connection
        model_name: Name of the dbt model to research
        project_dir: Absolute path to the dbt project directory

    Returns:
        Structured blueprint with contract, cardinalities, sibling patterns,
        status columns, and a recommended driving table.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'."
    if not project_dir or not _SAFE_DIR_RE.match(project_dir):
        return f"Error: Invalid project_dir '{project_dir}'."

    proj = Path(project_dir)
    if not proj.exists():
        return f"Error: Project directory '{project_dir}' does not exist."

    # ------------------------------------------------------------------
    # Phase 1: Filesystem — YML contract + sibling SQL (deterministic)
    # ------------------------------------------------------------------
    contract = _find_yml_contract(proj, model_name)
    siblings = _read_sibling_sql(proj, model_name)
    model_sql_path = _find_model_sql(proj, model_name)
    model_sql = ""
    if model_sql_path and model_sql_path.exists():
        model_sql = model_sql_path.read_text()[:3000]

    # ------------------------------------------------------------------
    # Phase 2: Database — cardinalities + status columns
    # ------------------------------------------------------------------
    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            available = [c.name for c in await store.list_connections()]
            return f"Error: Connection '{connection_name}' not found. Available: {available}"

        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials for this connection."
        extras = await store.get_credential_extras(connection_name)

    from gateway.connectors.pool_manager import pool_manager

    async def _query(sql: str) -> list:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras,
            connection_name=connection_name,
        ) as connector:
            return await connector.execute(sql)

    # Discover all tables and their columns
    try:
        all_tables_rows = await _query("SHOW TABLES")
        all_tables = [r[list(r.keys())[0]] for r in all_tables_rows]
    except Exception as e:
        return f"Error listing tables: {sanitize_mcp_error(str(e))}"

    table_columns: dict[str, list[str]] = {}
    for tbl in all_tables:
        try:
            col_rows = await _query(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name = '{tbl}' ORDER BY ordinal_position"
            )
            table_columns[tbl] = [r["column_name"] for r in col_rows]
        except Exception:
            table_columns[tbl] = []

    # Identify upstream tables from refs/sources in contract.
    # If a ref isn't materialized (stub/missing), trace through its SQL
    # to find the raw source tables it depends on.
    upstream_names: list[str] = []
    unmaterialized_refs: list[str] = []

    for ref_name in contract.get("refs", []):
        match = next((t for t in all_tables if t.lower() == ref_name.lower()), None)
        if match:
            upstream_names.append(match)
        else:
            unmaterialized_refs.append(ref_name)

    for schema_name, table_name in contract.get("sources", []):
        match = next((t for t in all_tables if t.lower() == table_name.lower()), None)
        if match:
            upstream_names.append(match)

    # Trace unmaterialized refs: read their SQL to find THEIR sources/refs
    for unmat_ref in unmaterialized_refs:
        ref_sql_path = _find_model_sql(proj, unmat_ref)
        if not ref_sql_path or not ref_sql_path.exists():
            continue
        ref_sql_text = ref_sql_path.read_text()
        # Find sources in the unmaterialized ref's SQL
        for _, src_table in re.findall(
            r"{{\s*source\(['\"](\w+)['\"],\s*['\"](\w+)['\"]\)\s*}}", ref_sql_text
        ):
            match = next((t for t in all_tables if t.lower() == src_table.lower()), None)
            if match and match not in upstream_names:
                upstream_names.append(match)
        # Find refs in the unmaterialized ref's SQL (one level deep)
        for nested_ref in re.findall(r"{{\s*ref\(['\"](\w+)['\"]\)\s*}}", ref_sql_text):
            match = next((t for t in all_tables if t.lower() == nested_ref.lower()), None)
            if match and match not in upstream_names:
                upstream_names.append(match)

    # Fallback: if still no upstreams, use tables sharing column names with YML
    if not upstream_names:
        contract_cols = {c["name"].lower() for c in contract.get("columns", [])}
        for tbl in all_tables:
            if tbl == model_name:
                continue
            tbl_cols_lower = {c.lower() for c in table_columns.get(tbl, [])}
            overlap = contract_cols & tbl_cols_lower
            if len(overlap) >= 2:
                upstream_names.append(tbl)

    # Query cardinalities for upstream tables
    cardinalities: list[dict] = []
    for tbl in upstream_names[:6]:
        card = await _query_cardinalities(_query, tbl, table_columns.get(tbl, []))
        cardinalities.append(card)

    # Discover status/flag columns in materialized upstream tables
    status_discoveries: list[dict] = []
    for tbl in upstream_names[:6]:
        discoveries = await _discover_status_columns(
            _query, tbl, table_columns.get(tbl, [])
        )
        status_discoveries.extend(discoveries)

    # Also discover status columns in unmaterialized intermediate models
    # by parsing their SQL for column aliases that rename raw status columns.
    # This catches patterns like `l_returnflag as item_status` in intermediates
    # that the agent will query but that aren't yet in the database.
    for unmat_ref in unmaterialized_refs:
        ref_sql_path = _find_model_sql(proj, unmat_ref)
        if not ref_sql_path or not ref_sql_path.exists():
            continue
        ref_sql_text = ref_sql_path.read_text()
        # Find "X as Y" aliases where Y matches a status column name
        aliases = re.findall(
            r'(\w+)\s+[Aa][Ss]\s+(\w+)', ref_sql_text
        )
        for raw_col, alias in aliases:
            if alias.lower() in _STATUS_COL_PATTERNS:
                # Find the raw source table that has the original column
                for src_tbl in upstream_names:
                    src_cols = table_columns.get(src_tbl, [])
                    if raw_col in src_cols or raw_col.lower() in {c.lower() for c in src_cols}:
                        # Query the actual values from the raw source
                        try:
                            safe_col = raw_col.replace('"', '""')
                            rows = await _query(
                                f'SELECT DISTINCT "{safe_col}" AS val '
                                f'FROM {_quote_table(src_tbl)} ORDER BY 1 LIMIT 20'
                            )
                            values = [r["val"] for r in rows] if rows else []
                            status_discoveries.append({
                                "column": f"{alias} (from {raw_col})",
                                "table": unmat_ref,
                                "values": values,
                            })
                        except Exception:
                            pass
                        break

    # ------------------------------------------------------------------
    # Phase 3: Recommend driving table
    # ------------------------------------------------------------------
    # The driving table is the upstream with the most rows that shares
    # a key column with the model's primary/unique key.
    contract_col_names = [c["name"] for c in contract.get("columns", [])]
    unique_cols = [
        c["name"] for c in contract.get("columns", [])
        if "unique" in c.get("tests", [])
    ]
    primary_key = unique_cols[0] if unique_cols else None

    driving_table = None
    driving_rows = 0
    for card in cardinalities:
        tbl = card["table"]
        rows = card["total_rows"]
        if primary_key:
            tbl_cols_lower = {c.lower() for c in table_columns.get(tbl, [])}
            if primary_key.lower() in tbl_cols_lower and rows > driving_rows:
                driving_table = tbl
                driving_rows = rows
        elif rows > driving_rows:
            driving_table = tbl
            driving_rows = rows

    # ------------------------------------------------------------------
    # Phase 4: Format output
    # ------------------------------------------------------------------
    lines: list[str] = [f"## Model Blueprint: {model_name}", ""]

    # Contract
    if contract["description"]:
        lines.append(f"**Description:** {contract['description']}")
    if contract["columns"]:
        lines.append(f"**YML columns ({len(contract['columns'])}):**")
        for col in contract["columns"]:
            tests_str = f" [{', '.join(col['tests'])}]" if col["tests"] else ""
            desc_str = f" — {col['description']}" if col["description"] else ""
            lines.append(f"  - `{col['name']}`{tests_str}{desc_str}")
    lines.append("")

    # Existing SQL
    if model_sql:
        lines.append("**Existing SQL (stub or complete):**")
        lines.append(f"```sql\n{model_sql}\n```")
        lines.append("")

    # Unmaterialized refs (need building first)
    if unmaterialized_refs:
        lines.append("**Unmaterialized refs (build these FIRST):**")
        for ref_name in unmaterialized_refs:
            ref_sql_path = _find_model_sql(proj, ref_name)
            if ref_sql_path:
                lines.append(f"  - `{ref_name}` — SQL exists at {ref_sql_path.relative_to(proj)}")
            else:
                lines.append(f"  - `{ref_name}` — NO SQL FILE (must be created)")
        lines.append("")

    # Upstream cardinalities
    if cardinalities:
        lines.append("**Upstream tables:**")
        for card in cardinalities:
            tbl = card["table"]
            rows = card["total_rows"]
            keys = ", ".join(
                f"{k}={v:,}" for k, v in card["key_counts"].items()
            )
            marker = " ← DRIVING TABLE" if tbl == driving_table else ""
            lines.append(f"  - `{tbl}`: {rows:,} rows ({keys}){marker}")
        lines.append("")

    # Status/flag column discoveries — with entity count per status value
    if status_discoveries:
        lines.append("**⚠ STATUS/FLAG COLUMNS FOUND — DO NOT aggregate without filtering:**")
        for disc in status_discoveries:
            vals = ", ".join(str(v) for v in disc["values"][:10])
            lines.append(f"  - `{disc['table']}.{disc['column']}`: [{vals}]")

            # Show distinct entity counts per status value and with exclusions
            # This helps the agent see exactly how row counts change with filters
            raw_col = disc["column"]
            tbl = disc["table"]
            # Extract the actual column name (strip "alias (from raw)" format)
            actual_col = raw_col.split(" (from ")[0] if " (from " in raw_col else raw_col
            source_col = raw_col.split("(from ")[-1].rstrip(")") if "(from " in raw_col else raw_col
            # Find the key column to count distinct on
            key_col = primary_key or "customer_id"

            # Try to compute counts per status value from raw source
            for src_tbl in upstream_names:
                src_cols = table_columns.get(src_tbl, [])
                src_col_match = next((c for c in src_cols if c.lower() == source_col.lower()), None)
                key_match = next(
                    (c for c in src_cols if
                     c.lower().endswith("custkey") or
                     c.lower() == "customer_id" or
                     (c.lower().endswith("_id") and "cust" in c.lower())),
                    None,
                )
                # Fallback: if no customer key in this table, try joining through orders
                if not key_match:
                    # Look for an orderkey that can join to orders.o_custkey
                    order_key = next((c for c in src_cols if "orderkey" in c.lower() or "order_id" in c.lower()), None)
                    if order_key and "orders" in {t.lower() for t in upstream_names}:
                        orders_tbl = next(t for t in upstream_names if t.lower() == "orders")
                        # Use a join to count distinct customers per status
                        try:
                            count_rows = await _query(
                                f'SELECT "{src_col_match}" AS status_val, '
                                f'COUNT(DISTINCT o.o_custkey) AS entity_count '
                                f'FROM {_quote_table(src_tbl)} s '
                                f'JOIN {_quote_table(orders_tbl)} o ON s."{order_key}" = o.o_orderkey '
                                f'GROUP BY 1 ORDER BY 2 DESC'
                            )
                            if count_rows:
                                total_entities = sum(r["entity_count"] for r in count_rows)
                                lines.append(f"    Customer counts by {src_col_match} (via orders join):")
                                for r in count_rows:
                                    lines.append(f"      {r['status_val']}: {r['entity_count']:,} customers")
                                for r in count_rows:
                                    try:
                                        safe_val = str(r["status_val"]).replace("'", "''")
                                        ex_row = await _query(
                                            f'SELECT COUNT(DISTINCT o.o_custkey) AS cnt '
                                            f'FROM {_quote_table(src_tbl)} s '
                                            f'JOIN {_quote_table(orders_tbl)} o ON s."{order_key}" = o.o_orderkey '
                                            f"""WHERE s."{src_col_match}" != '{safe_val}'"""
                                        )
                                        if ex_row:
                                            lines.append(
                                                f"    Excluding {r['status_val']}: "
                                                f"{ex_row[0]['cnt']:,} customers"
                                            )
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        continue
                if not src_col_match or not key_match:
                    continue
                try:
                    count_rows = await _query(
                        f'SELECT "{src_col_match}" AS status_val, '
                        f'COUNT(DISTINCT "{key_match}") AS entity_count '
                        f'FROM {_quote_table(src_tbl)} '
                        f'GROUP BY 1 ORDER BY 2 DESC'
                    )
                    if count_rows:
                        total = sum(r["entity_count"] for r in count_rows)
                        lines.append(f"    Entity counts by status (total {total:,} distinct):")
                        for r in count_rows:
                            lines.append(f"      {r['status_val']}: {r['entity_count']:,}")
                        # Show count excluding each value
                        for r in count_rows:
                            excluded = total - r["entity_count"]
                            # But entities can appear in multiple statuses, so compute properly
                            try:
                                safe_val = str(r["status_val"]).replace("'", "''")
                                ex_row = await _query(
                                    f'SELECT COUNT(DISTINCT "{key_match}") AS cnt '
                                    f'FROM {_quote_table(src_tbl)} '
                                    f"""WHERE "{src_col_match}" != '{safe_val}'"""
                                )
                                if ex_row:
                                    lines.append(
                                        f"    Excluding {r['status_val']}: "
                                        f"{ex_row[0]['cnt']:,} distinct entities"
                                    )
                            except Exception:
                                pass
                except Exception:
                    pass
                break

        lines.append("")

    # Driving table recommendation
    if driving_table:
        lines.append(f"**Recommended driving table:** `{driving_table}` ({driving_rows:,} rows)")
        if primary_key:
            lines.append(f"  Primary key: `{primary_key}` — use as FROM, LEFT JOIN others.")
        lines.append("")

    # Sibling SQL patterns
    if siblings:
        lines.append(f"**Sibling models ({len(siblings)}):**")
        for sib in siblings:
            lines.append(f"\n### {sib['name']}.sql")
            lines.append(f"```sql\n{sib['sql']}\n```")
        lines.append("")

    # Other available tables (not in upstream refs — may be useful lookup/dim tables)
    other_tables = [
        t for t in all_tables
        if t != model_name and t not in upstream_names
    ]
    if other_tables:
        lines.append(f"**Other tables in database ({len(other_tables)}):**")
        for tbl in other_tables[:10]:
            cols = table_columns.get(tbl, [])
            try:
                row = await _query(f"SELECT COUNT(*) AS cnt FROM {_quote_table(tbl)}")
                cnt = row[0]["cnt"] if row else 0
            except Exception:
                cnt = 0
            col_preview = ", ".join(cols[:6])
            if len(cols) > 6:
                col_preview += f", ... ({len(cols)} total)"
            lines.append(f"  - `{tbl}`: {cnt:,} rows — {col_preview}")
        lines.append("")

    return "\n".join(lines)
