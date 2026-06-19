"""map_columns — consolidated, any-DB upstream column mapper (MCP tool).

A catch-all replacement for the local DuckDB `map-columns` bin script: in ONE call
it lists every upstream column for a dbt model, profiles each (null/distinct),
classifies it MAPPED / UNMAPPED-INCLUDE / UNMAPPED-EXCLUDE against the YML contract,
detects lookup joins and column collisions. The classification/output logic is a
faithful port of the script; only the database layer is swapped from a local
`.duckdb` file to the gateway connector (so it works against any database), and
filesystem reads (model SQL, YML) use `project_dir` — the same pattern the former
generate_model_blueprint tool used.
"""

from __future__ import annotations

import re
from pathlib import Path

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.mcp.validation import _MODEL_NAME_RE, _validate_connection_name

SKIP_DIRS = (".claude", "dbt_packages", "target", "__pycache__")
BINARY_TYPES = {"BLOB", "BYTEA", "BINARY", "VARBINARY", "IMAGE"}
_SAFE_DIR_RE = re.compile(r"^[A-Za-z0-9_./\\:-]{1,512}$")


# ── pure filesystem / parsing helpers (verbatim from the bin script) ────────
def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def _extract_yml_columns(work_dir: Path, model_name: str) -> list[str]:
    columns: list[str] = []
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in SKIP_DIRS):
                continue
            try:
                text = _read_text(yml_file)
            except Exception:
                continue
            current_model = None
            in_columns = False
            for line in text.splitlines():
                stripped = line.lstrip()
                indent = len(line) - len(stripped)
                m = re.match(r"-\s*name:\s*(\S+)", stripped)
                if m and 1 <= indent <= 4:
                    current_model = m.group(1)
                    in_columns = False
                    continue
                if current_model == model_name and stripped.startswith("columns:"):
                    in_columns = True
                    continue
                if in_columns and indent <= 4 and stripped and not stripped.startswith("-"):
                    in_columns = False
                    continue
                if in_columns and current_model == model_name:
                    cm = re.match(r"-\s*name:\s*(\S+)", stripped)
                    if cm:
                        columns.append(cm.group(1))
    return columns


def _extract_refs(sql_text: str) -> list[str]:
    return re.findall(r"\{\{\s*ref\(['\"](\w+)['\"]\)\s*\}\}", sql_text)


def _extract_sources(sql_text: str) -> list[tuple[str, str]]:
    return re.findall(r"\{\{\s*source\(['\"](\w+)['\"]\s*,\s*['\"](\w+)['\"]\)\s*\}\}", sql_text)


def _get_source_identifier(work_dir: Path, source_name: str, table_name: str) -> str:
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in SKIP_DIRS):
                continue
            try:
                text = _read_text(yml_file)
            except Exception:
                continue
            in_source = False
            in_tables = False
            found_table = False
            for line in text.splitlines():
                stripped = line.lstrip()
                m = re.match(r"-\s*name:\s*(\S+)", stripped)
                if m and not in_tables:
                    in_source = m.group(1) == source_name
                    continue
                if in_source and stripped.startswith("tables:"):
                    in_tables = True
                    continue
                if in_tables and m:
                    found_table = m.group(1) == table_name
                    continue
                if found_table and stripped.startswith("identifier"):
                    ident = stripped.split(":", 1)[1].strip().strip("'\"")
                    if ident:
                        return ident
    return table_name


def _parse_sql_columns(sql: str) -> list[tuple[str, str]]:
    clean = re.sub(r"\{\{.*?\}\}", "___REF___", sql)
    clean = re.sub(r"\{%.*?%\}", "", clean)
    clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)
    clean = re.sub(r"--.*$", "", clean, flags=re.MULTILINE)
    matches = list(re.finditer(r"SELECT\s+(.*?)\s+FROM\b", clean, re.IGNORECASE | re.DOTALL))
    if not matches:
        return []
    sel_text = matches[-1].group(1)
    if sel_text.strip() == "*":
        return []
    depth = 0
    current: list[str] = []
    parts: list[str] = []
    for ch in sel_text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current).strip())
    cols: list[tuple[str, str]] = []
    for part in parts:
        part = re.sub(r"--.*$", "", part.strip(), flags=re.MULTILINE).strip()
        if not part or part == "*":
            continue
        as_match = re.search(r"\bAS\s+(\w+)\s*$", part, re.IGNORECASE)
        if as_match:
            cols.append((as_match.group(1), "VARCHAR"))
        else:
            words = part.split()
            name = words[-1].split(".")[-1] if words else ""
            if name and name != "___REF___" and name.upper() not in (
                "THEN", "ELSE", "END", "WHEN", "CASE", "AND", "OR", "NOT",
                "NULL", "TRUE", "FALSE", "AS", "FROM", "WHERE", "SELECT",
            ):
                cols.append((name, "VARCHAR"))
    return cols


def _classify_column(col_name, col_type, profile, exclude_set, has_yml_contract, system_cols=None):
    cl = col_name.lower()
    if cl in exclude_set:
        return "UNMAPPED-EXCLUDE", "agent_blacklist"
    warning = ""
    is_binary = col_type.upper() in BINARY_TYPES
    is_all_null = False
    if profile:
        stats = profile.get(col_name, {})
        total = stats.get("total", 0)
        if total > 0:
            if stats.get("null_count", 0) == total:
                is_all_null = True
            elif stats.get("distinct_count", 0) == 1 and stats.get("null_count", 0) == 0:
                warning = "constant_value"
    if is_binary and is_all_null:
        return "UNMAPPED-EXCLUDE", "all_null_binary"
    if is_binary:
        warning = "binary_type"
    elif is_all_null:
        if system_cols:
            sc = system_cols.get(cl, {})
            if sc.get("tables", 0) > 1 and not sc.get("has_data_anywhere", False):
                return "UNMAPPED-EXCLUDE", "unused_system_column"
            warning = "all_null"
        else:
            warning = "all_null"
    if col_type.upper() == "VARCHAR" and not warning:
        if cl.endswith(("_date", "_on", "_at")):
            if any(w in cl for w in ("modified", "updated", "changed")):
                warning = "varchar_audit_timestamp→keep_as_VARCHAR"
            elif any(w in cl for w in ("created", "order", "ship", "paid")):
                warning = "varchar_event_date→CAST_to_DATE"
    return "UNMAPPED-INCLUDE", warning


def _infer_prefix(model_name: str, upstream_name: str) -> str:
    for domain in ["klaviyo", "shopify", "facebook", "instagram", "twitter", "linkedin",
                   "google", "hubspot", "salesforce", "stripe", "twilio", "pendo", "jira",
                   "asana", "xero", "zuora", "recharge", "quickbooks"]:
        if domain in upstream_name.lower():
            return domain + "_"
    return ""


def _detect_collisions(all_upstream_cols):
    col_to_upstreams: dict[str, list[str]] = {}
    for upstream, col_name, _, status in all_upstream_cols:
        if status == "UNMAPPED-EXCLUDE":
            continue
        cl = col_name.lower()
        col_to_upstreams.setdefault(cl, [])
        if upstream not in col_to_upstreams[cl]:
            col_to_upstreams[cl].append(upstream)
    return {col: ups for col, ups in col_to_upstreams.items() if len(ups) > 1}


def _find_driving_ref(sql_text: str):
    m = re.search(r"\bFROM\s+\{\{\s*ref\(['\"](\w+)['\"]\)\s*\}\}", sql_text, re.IGNORECASE)
    return m.group(1) if m else None


# ── connector-backed DB layer (any-DB; replaces the .duckdb queries) ─────────
class _Schema:
    """Cached connector schema: table resolution + columns (any database)."""

    def __init__(self, raw: dict, dialect: str = "duckdb"):
        self.dialect = (dialect or "duckdb").lower()
        self._raw = raw  # {"schema.table": {"name","columns":[{name,type}], "row_count"}}
        self._by_lower: dict[str, str] = {}
        for key, t in raw.items():
            self._by_lower[key.lower()] = key
            self._by_lower[t.get("name", key.split(".")[-1]).lower()] = key

    def tables(self) -> list[str]:
        return [t.get("name", k.split(".")[-1]) for k, t in self._raw.items()]

    def resolve(self, name: str) -> str | None:
        return self._by_lower.get(name.lower())

    def columns(self, name: str) -> list[tuple[str, str]]:
        key = self.resolve(name)
        if not key:
            return []
        return [(c["name"], (c.get("type") or "").upper()) for c in self._raw[key].get("columns", [])]

    def row_count(self, name: str) -> int:
        key = self.resolve(name)
        return int(self._raw[key].get("row_count", 0)) if key else 0

    def distinct(self, name: str, col: str) -> int | None:
        """Catalog distinct-count for a column (from get_schema stats), or None."""
        key = self.resolve(name)
        if not key:
            return None
        for c in self._raw[key].get("columns", []):
            if c["name"].lower() == col.lower():
                st = c.get("stats", {})
                if st.get("distinct_count") is not None:
                    return int(st["distinct_count"])
                if st.get("distinct_fraction") is not None:
                    return int(abs(st["distinct_fraction"]) * self.row_count(name))
                return None
        return None


async def _q(connector, sql: str) -> list[tuple]:
    """Run a query and return rows as tuples in select order (mirrors fetchall())."""
    rows = await connector.execute(sql)
    return [tuple(r.values()) for r in rows]


def _get_db_columns(schema: _Schema, work_dir: Path, table_name: str) -> list[tuple[str, str]]:
    cols = schema.columns(table_name)
    if cols:
        return cols
    # Fallback: parse the model's SQL file (not materialized yet)
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        if sql_file.stem.lower() == table_name.lower():
            try:
                return _parse_sql_columns(_read_text(sql_file))
            except Exception:
                return []
    return []


# Dialect groups for the profiling strategy.
_PG_STATS = {"postgres", "redshift"}            # have pg_stats (null_frac, n_distinct) — no scan
_COLUMNAR = {"duckdb", "sqlite", "clickhouse"}  # exact is cheap; DuckDB stays 1-1 with the script
_BIG = 2_000_000                                # above this, sample row-store tables
_SAMPLE = 200_000                               # bounded sample size for the exact path


async def _profile_pg_stats(connector, schema, key, columns, rows) -> dict[str, dict]:
    """Postgres/Redshift: read null_frac + n_distinct from the catalog (no scan)."""
    sch, tbl = key.split(".", 1) if "." in key else ("public", key)

    stats: dict[str, tuple] = {}
    try:
        rows_res = await connector.execute(
            "SELECT attname, null_frac, n_distinct FROM pg_stats "
            "WHERE schemaname = $1 AND tablename = $2",
            [sch, tbl],
        )
        for r in rows_res:
            stats[r["attname"]] = (r["null_frac"], r["n_distinct"])
    except Exception:
        stats = {}
    out: dict[str, dict] = {}
    missing: list[tuple[str, str]] = []
    for c, t in columns:
        s = stats.get(c)
        if not s:
            missing.append((c, t))
            continue
        nf = float(s[0] or 0)
        nd = float(s[1] or 0)
        distinct = int(nd) if nd > 0 else (int(abs(nd) * rows) if nd < 0 else 0)
        out[c] = {"null_count": int(nf * rows), "distinct_count": distinct, "total": rows}
    if missing:  # never-analyzed columns → bounded sample
        out.update(await _profile_exact(connector, schema, key, missing, sample_rows=_SAMPLE))
    return out


async def _profile_exact(connector, schema, key, columns, sample_rows: int | None = None) -> dict[str, dict]:
    """One batched scan: exact null + COUNT(DISTINCT). Optionally over a sample.

    Identifier quoting uses the connector's own dialect rules (double-quote /
    backtick / brackets), so this is correct on every supported database.
    """
    if sample_rows is not None:
        sample_rows = int(sample_rows)
    qt = connector.quote_table(key)
    qc = connector.quote_identifier
    src = qt
    if sample_rows:
        cols_sel = ", ".join(qc(c) for c, _ in columns)
        if schema.dialect == "mssql":
            src = f"(SELECT TOP {sample_rows} {cols_sel} FROM {qt}) _s"
        else:
            src = f"(SELECT {cols_sel} FROM {qt} LIMIT {sample_rows}) _s"
    selects = ["COUNT(*) AS total"]
    for i, (c, _) in enumerate(columns):
        selects.append(f"COUNT({qc(c)}) AS nn{i}")
        selects.append(f"COUNT(DISTINCT {qc(c)}) AS d{i}")
    try:
        res = await connector.execute(f"SELECT {', '.join(selects)} FROM {src}")
        row = res[0]
    except Exception:
        return {}
    total = row["total"]
    out: dict[str, dict] = {}
    for i, (c, _) in enumerate(columns):
        nn = row[f"nn{i}"] or 0
        out[c] = {"null_count": total - nn, "distinct_count": row[f"d{i}"] or 0, "total": total}
    return out


async def _profile_columns(connector, schema: _Schema, table_name: str,
                           columns: list[tuple[str, str]]) -> dict[str, dict]:
    """null_count / distinct_count / total per column — dialect-aware, any DB.

    - Postgres/Redshift large tables: catalog stats (pg_stats), no scan.
    - DuckDB/SQLite/ClickHouse and all small tables: exact (DuckDB stays 1-1).
    - Other row-store DBs above the threshold: exact over a bounded sample.
    """
    if not columns:
        return {}
    key = schema.resolve(table_name)
    if not key:
        return {}
    rows = schema.row_count(table_name)
    if schema.dialect in _PG_STATS and rows > _BIG:
        return await _profile_pg_stats(connector, schema, key, columns, rows)
    sample = _SAMPLE if (rows > _BIG and schema.dialect not in _COLUMNAR) else None
    return await _profile_exact(connector, schema, key, columns, sample_rows=sample)


def _detect_lookups(connector, schema: _Schema) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    all_tables = set(schema.tables())
    for tbl in sorted(all_tables):
        for col_name, _ in schema.columns(tbl):
            low = col_name.lower()
            if low.endswith("_ids"):
                prefix = low[:-4]
            elif low.endswith("_id") and low != "id":
                prefix = low[:-3]
            else:
                continue
            for candidate in all_tables:
                cl = candidate.lower()
                if cl in (f"{prefix}s", f"stg_{prefix}s", f"{prefix}", f"stg_{prefix}", f"dim_{prefix}s"):
                    if candidate == tbl:
                        continue
                    lk_cols = [c for c, _ in schema.columns(candidate)]
                    name_cols = [c for c in lk_cols if "name" in c.lower() or "company" in c.lower()]
                    id_col = next((c for c in lk_cols if c.lower() == "id"), None)
                    if name_cols and id_col:
                        display = name_cols[0]
                        alias = f"{prefix}_{display}" if not display.lower().startswith(prefix) else display
                        result[low] = (candidate, id_col, alias)
                    break
    return result


async def _detect_system_columns(connector, schema: _Schema) -> dict[str, dict]:
    col_stats: dict[str, dict] = {}
    raw_tables = [t for t in schema.tables() if not any(t.lower().startswith(p) for p in _MODEL_PREFIXES)]
    for tbl in raw_tables:
        cols = schema.columns(tbl)
        if not cols:
            continue
        prof = await _profile_columns(connector, schema, tbl, cols)
        for name, _ in cols:
            cl = name.lower()
            st = col_stats.setdefault(cl, {"tables": 0, "has_data_anywhere": False})
            st["tables"] += 1
            p = prof.get(name, {})
            if (p.get("total", 0) - p.get("null_count", 0)) > 0:
                st["has_data_anywhere"] = True
    return col_stats


# ── core mapping (port of map_model / map_upstreams; print → out.append) ─────
async def _map_model(connector, schema, work_dir, model_name, exclude_set) -> list[str]:
    out: list[str] = []
    is_obt = model_name.lower().startswith("obt_")
    is_dim_model = model_name.lower().startswith("dim_")
    system_cols = await _detect_system_columns(connector, schema) if is_obt else {}

    sql_file = None
    for f in work_dir.rglob("*.sql"):
        if any(skip in str(f) for skip in SKIP_DIRS):
            continue
        if f.stem == model_name:
            sql_file = f
            break
    if not sql_file:
        return [f"## {model_name}", "SQL file not found.", ""]

    sql_text = _read_text(sql_file)
    yml_columns = set(_extract_yml_columns(work_dir, model_name))
    yml_columns_lower = {c.lower() for c in yml_columns}
    refs = _extract_refs(sql_text)
    sources = _extract_sources(sql_text)
    driving_ref = _find_driving_ref(sql_text) if is_obt else None
    lookups = _detect_lookups(connector, schema)

    out.append(f"## Column Map: {model_name}")
    out.append(f"YML contract: {len(yml_columns)} columns" if yml_columns
               else "YML contract: NONE (no columns defined in YML)")
    out.append("")

    all_upstream_cols: list[tuple[str, str, str, str]] = []

    lookup_upstreams: dict[str, str] = {}
    if is_dim_model:
        model_entity = model_name.lower()
        for pfx in ("dim_", "fact_", "stg_", "int_", "obt_", "fct_"):
            if model_entity.startswith(pfx):
                model_entity = model_entity[len(pfx):]
                break
        for _lk_col, (lk_tbl, _lk_key, lk_alias) in lookups.items():
            for ref_name in refs:
                ref_lower = ref_name.lower()
                if ref_lower in (lk_tbl.lower(), f"stg_{lk_tbl.lower()}"):
                    ref_entity = ref_lower
                    for pfx in ("dim_", "fact_", "stg_", "int_", "obt_", "fct_"):
                        if ref_entity.startswith(pfx):
                            ref_entity = ref_entity[len(pfx):]
                            break
                    if ref_entity == model_entity or model_entity in ref_entity:
                        continue
                    lookup_upstreams[ref_name] = lk_alias
                    break

    for ref_name in sorted(set(refs)):
        db_cols = _get_db_columns(schema, work_dir, ref_name)
        if not db_cols:
            out.append(f"### Upstream: ref('{ref_name}') — NO COLUMNS FOUND (not materialized?)")
            out.append("")
            continue
        prefix = _infer_prefix(model_name, ref_name)
        profile = await _profile_columns(connector, schema, ref_name, db_cols)
        is_driving = is_obt and ref_name == driving_ref
        is_dim = is_obt and not is_driving
        is_lookup_upstream = ref_name in lookup_upstreams
        lookup_display_alias = lookup_upstreams.get(ref_name, "").lower() if is_lookup_upstream else ""
        lookup_display_cols: set[str] = set()
        if lookup_display_alias:
            lookup_display_cols.add(lookup_display_alias)
            for c in [r[0] for r in db_cols]:
                if c.lower() in lookup_display_alias or lookup_display_alias.endswith(c.lower()):
                    lookup_display_cols.add(c.lower())
        label = "driving" if is_driving else ("dim" if is_dim else "")
        if is_lookup_upstream:
            label = "lookup"
        tag = f" ({label})" if label else ""
        out.append(f"### Upstream: ref('{ref_name}'){tag} — {len(db_cols)} columns")
        for col_name, col_type in db_cols:
            prefixed = prefix + col_name if prefix else col_name
            if col_name.lower() in yml_columns_lower or prefixed.lower() in yml_columns_lower:
                status, reason = "MAPPED", ""
                target = col_name if col_name.lower() in yml_columns_lower else prefixed
            else:
                status, reason = _classify_column(col_name, col_type, profile, exclude_set, bool(yml_columns), system_cols)
                target = prefixed if prefix else col_name
            if is_lookup_upstream and col_name.lower() not in lookup_display_cols:
                status, reason = "UNMAPPED-EXCLUDE", "lookup_table_col"
            reason_tag = f" [{reason}]" if reason else ""
            lookup_info = lookups.get(col_name.lower())
            if lookup_info and is_dim_model and not is_lookup_upstream:
                lk_tbl, lk_key, lk_alias = lookup_info
                out.append(f"  {col_name} ({col_type}) → UNMAPPED-EXCLUDE [lookup_join_key: JOIN {lk_tbl} ON {lk_tbl}.{lk_key}, output {lk_alias} instead]")
            elif reason and "CAST_to_DATE" in reason:
                out.append(f"  {col_name} ({col_type}) → UNMAPPED-INCLUDE [varchar_event_date]")
            elif reason and "keep_as_VARCHAR" in reason:
                out.append(f"  {col_name} ({col_type}) → UNMAPPED-INCLUDE [varchar_audit_timestamp]")
            else:
                out.append(f"  {col_name} ({col_type}) → {status}{reason_tag}: {target}")
            all_upstream_cols.append((ref_name, col_name, col_type, status))
        out.append("")

    for source_name, table_name in sorted(set(sources)):
        identifier = _get_source_identifier(work_dir, source_name, table_name)
        db_cols = _get_db_columns(schema, work_dir, identifier) or _get_db_columns(schema, work_dir, table_name)
        if not db_cols:
            out.append(f"### Upstream: source('{source_name}', '{table_name}') — NO COLUMNS FOUND")
            out.append("")
            continue
        profile = await _profile_columns(connector, schema, identifier if identifier != table_name else table_name, db_cols)
        out.append(f"### Upstream: source('{source_name}', '{table_name}') — {len(db_cols)} columns")
        for col_name, col_type in db_cols:
            if col_name.lower() in yml_columns_lower:
                status, reason = "MAPPED", ""
            else:
                status, reason = _classify_column(col_name, col_type, profile, exclude_set, bool(yml_columns), system_cols)
            reason_tag = f" [{reason}]" if reason else ""
            lookup_info = lookups.get(col_name.lower())
            if lookup_info and is_dim_model:
                lk_tbl, lk_key, lk_alias = lookup_info
                out.append(f"  {col_name} ({col_type}) → UNMAPPED-EXCLUDE [lookup_join_key: JOIN {lk_tbl} ON {lk_tbl}.{lk_key}, output {lk_alias} instead]")
            elif reason and "CAST_to_DATE" in reason:
                out.append(f"  {col_name} ({col_type}) → UNMAPPED-INCLUDE [varchar_event_date]")
            elif reason and "keep_as_VARCHAR" in reason:
                out.append(f"  {col_name} ({col_type}) → UNMAPPED-INCLUDE [varchar_audit_timestamp]")
            else:
                out.append(f"  {col_name} ({col_type}) → {status}{reason_tag}: {col_name}")
            all_upstream_cols.append((f"{source_name}.{table_name}", col_name, col_type, status))
        out.append("")

    collisions = _detect_collisions(all_upstream_cols)
    if collisions:
        out.append("### COLLISIONS — duplicate column names across upstreams")
        for col, upstreams in sorted(collisions.items()):
            out.append(f"  {col} — appears in: {', '.join(upstreams)}")
        out.append("")

    mapped = sum(1 for _, _, _, s in all_upstream_cols if s == "MAPPED")
    excluded = sum(1 for _, _, _, s in all_upstream_cols if s == "UNMAPPED-EXCLUDE")
    included = sum(1 for _, _, _, s in all_upstream_cols if s == "UNMAPPED-INCLUDE")
    out.append(f"### Summary: {len(all_upstream_cols)} upstream columns — {mapped} mapped, {included} include, {excluded} exclude")
    if collisions:
        out.append(f"### COLLISIONS: {len(collisions)} column(s) appear in multiple upstreams — MUST alias")
    return out


@audited_tool(mcp)
async def map_columns(connection_name: str, model_name: str, project_dir: str,
                      exclude: str = "") -> str:
    """
    Map all upstream columns for a dbt model in one call (any database).

    Lists every upstream table's columns, profiles them (null rate, distinctness),
    and classifies each as MAPPED / UNMAPPED-INCLUDE / UNMAPPED-EXCLUDE against the
    model's YML contract, with lookup-join and collision detection. Run this BEFORE
    writing a model's SQL to decide which columns to include.

    Args:
        connection_name: Configured database connection.
        model_name: dbt model to map.
        project_dir: Absolute path to the dbt project directory (for YML/SQL).
        exclude: Optional comma-separated column names to force-exclude.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'."
    if not project_dir or not _SAFE_DIR_RE.match(project_dir):
        return f"Error: Invalid project_dir '{project_dir}'."
    work_dir = Path(project_dir)
    if not work_dir.exists():
        return f"Error: project_dir '{project_dir}' does not exist."
    exclude_set = {c.strip().lower() for c in exclude.split(",") if c.strip()}

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
            schema = _Schema(await connector.get_schema(), conn_info.db_type)
            lines = await _map_model(connector, schema, work_dir, model_name, exclude_set)
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"
    return "\n".join(lines)


# ── analyze_project_db — the DB half of the old scan_project, one call, any DB ──
_MODEL_PREFIXES = ("stg_", "dim_", "fact_", "int_", "obt_", "fct_", "solution__", "mart_", "auto_")
# Parent-child orphan detection uses catalog distinct-counts (pigeonhole), so it never
# scans a large table. Exact COUNT(DISTINCT) is only used as a fallback on small tables
# whose stats the catalog doesn't carry (e.g. DuckDB).
_DISTINCT_EXACT_CAP = 200_000


async def _staging_gaps(schema: _Schema) -> list[str]:
    """stg_* models that have fewer rows than the raw table they wrap (uses row-count
    estimates from the catalog — no scans)."""
    hints: list[str] = []
    tables = schema.tables()
    for tbl in sorted(tables):
        if not tbl.lower().startswith("stg_"):
            continue
        raw_name = tbl[4:].rstrip("s").lower()
        raw_match = next((c for c in tables if c.lower() in (raw_name, raw_name + "s", tbl[4:].lower())), None)
        if not raw_match:
            continue
        sc, rc = schema.row_count(tbl), schema.row_count(raw_match)
        if rc and sc and sc < rc:
            hints.append(f"  {tbl}: ~{sc} rows (raw {raw_match}: ~{rc} — staging filters "
                         f"~{rc - sc}). Use ref('{tbl}') not source().")
    return hints


# Columnar engines do exact COUNT(DISTINCT) cheaply at any size; MPP engines have a
# fast approximate-distinct function. Everything else is exact only on small tables.
_COLUMNAR_DISTINCT = {"duckdb", "clickhouse"}
_APPROX_DISTINCT_FN = {
    "snowflake": "APPROX_COUNT_DISTINCT", "bigquery": "APPROX_COUNT_DISTINCT",
    "databricks": "APPROX_COUNT_DISTINCT", "trino": "approx_distinct",
}


async def _distinct(connector, schema: _Schema, table: str, col: str) -> int | None:
    """Distinct-count for a column, fast on every engine and never scanning a huge table:
    catalog stats first (PG/Redshift/MSSQL), then columnar-exact, then MPP-approx, then
    exact on small tables. None only when none of those is cheaply available."""
    d = schema.distinct(table, col)
    if d is not None:
        return d  # catalog — no scan
    dialect = schema.dialect
    qc = connector._quote_identifier(col)
    if dialect in _COLUMNAR_DISTINCT:
        expr = f"COUNT(DISTINCT {qc})"          # columnar: exact is cheap at any size
    elif dialect in _APPROX_DISTINCT_FN:
        expr = f"{_APPROX_DISTINCT_FN[dialect]}({qc})"   # MPP: fast approximate
    elif schema.row_count(table) and schema.row_count(table) <= _DISTINCT_EXACT_CAP:
        expr = f"COUNT(DISTINCT {qc})"          # small row-store: exact ok
    else:
        return None                            # large row-store w/o stats — don't scan
    try:
        q = connector._quote_table(schema.resolve(table))
        return (await _q(connector, f"SELECT {expr} FROM {q}"))[0][0]
    except Exception:
        return None


async def _driving_table_gaps(connector, schema: _Schema, cap: int = 10) -> list[str]:
    """Parent-child pairs where some parents have NO children (drive FROM parent).

    Pigeonhole on catalog distinct-counts — NO table scans, any size: a child can
    reference at most distinct(child.fk) distinct parents, so if
    distinct(parent.id) > distinct(child.fk) then at least the difference are orphaned.
    distinct() reads stats already in get_schema (Postgres/Redshift/etc.) and only falls
    back to an exact COUNT(DISTINCT) on small tables the catalog can't answer for.
    """
    hints: list[str] = []
    tables = {t: [c for c, _ in schema.columns(t)] for t in schema.tables()}
    parents = {t: next((c for c in cols if c.lower() == "id"), None) for t, cols in tables.items()}
    parents = {t: c for t, c in parents.items() if c}
    checked: set[tuple[str, str, str]] = set()
    for child, ccols in tables.items():
        for fk in [c for c in ccols if c.lower().endswith("_id") and c.lower() != "id"]:
            prefix = fk.lower().replace("_id", "")
            for parent, pid in parents.items():
                if parent == child or (parent, child, fk) in checked:
                    continue
                checked.add((parent, child, fk))
                if prefix not in parent.lower():
                    continue  # plausibility filter (avoids N^2 work)
                pd = await _distinct(connector, schema, parent, pid)
                cd = await _distinct(connector, schema, child, fk)
                if pd is None or cd is None or pd <= cd:
                    continue
                hints.append(f"  {parent}.{pid} ↔ {child}.{fk}: ~{pd - cd} of {pd} parent keys are not "
                             f"referenced by {child} (some parents have no children). "
                             f"Drive FROM {parent} LEFT JOIN {child}.")
                if len(hints) >= cap:
                    return hints
    return hints


@audited_tool(mcp)
async def analyze_project_db(connection_name: str) -> str:
    """
    Database-side project analysis for dbt model building — one call, any database.

    Consolidates the DB-derived hints the local scanner used to compute: lookup-join
    opportunities (`_id` columns with matching dimension tables), staging-vs-raw row
    gaps, and parent-child driving-table hints (parents with childless rows). Cheap by
    design — name/catalog-based where possible, bounded joins on large tables.

    Args:
        connection_name: Configured database connection.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    async with _store_session() as store:
        conn_info = await store.get_connection(connection_name)
        if not conn_info:
            return f"Error: Connection '{connection_name}' not found."
        conn_str = await store.get_connection_string(connection_name)
        if not conn_str:
            return "Error: No credentials stored for this connection"
        extras = await store.get_credential_extras(connection_name)

    from gateway.connectors.pool_manager import pool_manager

    try:
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            schema = _Schema(await connector.get_schema(), conn_info.db_type)
            lookups = _detect_lookups(connector, schema)
            staging = await _staging_gaps(schema)
            driving = await _driving_table_gaps(connector, schema)
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    out: list[str] = [f"## DB analysis: {connection_name}"]
    if driving:
        out += ["", "AGGREGATION DRIVING TABLE (parent rows with NO children — drive FROM parent):", *driving]
    if staging:
        out += ["", "STAGING FILTERS (staging has fewer rows than raw — use ref() not source()):", *staging]
    if lookups:
        out += ["", "LOOKUP JOINS AVAILABLE (_id columns with matching dimension tables):"]
        out += [f"  {col} → JOIN {tbl} ON {tbl}.{key} → output {alias}"
                for col, (tbl, key, alias) in sorted(lookups.items())]
    if len(out) == 1:
        out.append("  (no lookup, staging-gap, or driving-table signals detected)")
    return "\n".join(out)
