"""Upstream column observations for dbt models.

It reports YML matches, source-only columns, profiles, lookup candidates, and
column collisions as observations.
"""

from __future__ import annotations

import os as _os
import re
import time
from pathlib import Path

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _store_session
from gateway.mcp.server import mcp
from gateway.mcp.validation import _MODEL_NAME_RE, _validate_connection_name

SKIP_DIRS = (".claude", "dbt_packages", "target", "__pycache__")
BINARY_TYPES = {"BLOB", "BYTEA", "BINARY", "VARBINARY", "IMAGE"}

_PROJECT_DIR_MAX_LEN = 512


def _resolve_workspace_root() -> Path:
    """Workspace root that `project_dir` must live under.

    Resolution order:
      1. $SP_WORKSPACE_ROOT — explicit operator config (cloud + multi-tenant).
      2. Path.cwd() — local fallback. Fail-closed for cloud deployments is enforced
         in the caller by checking SP_DEPLOYMENT_MODE.
    """
    raw = _os.environ.get("SP_WORKSPACE_ROOT")
    if raw:
        return Path(raw).resolve()
    return Path.cwd().resolve()


def _validated_project_dir(project_dir: str) -> tuple[Path | None, str | None]:
    """Return (resolved_path, None) if safe; (None, error_string) otherwise.

    Rules:
      - Length cap (defense-in-depth against pathological inputs).
      - Must resolve under the workspace root after Path.resolve() (follows symlinks).
      - In cloud mode (SP_DEPLOYMENT_MODE == "cloud"), require an explicit
        SP_WORKSPACE_ROOT — fail-closed rather than fall back to CWD which is the
        gateway process dir on cloud.
      - The resolved path must exist and be a directory.
    """
    if not project_dir or len(project_dir) > _PROJECT_DIR_MAX_LEN:
        return None, f"Error: Invalid project_dir (empty or > {_PROJECT_DIR_MAX_LEN} chars)."
    if _os.environ.get("SP_DEPLOYMENT_MODE") == "cloud" and not _os.environ.get(
        "SP_WORKSPACE_ROOT"
    ):
        return None, "Error: project_dir not permitted — SP_WORKSPACE_ROOT not configured."
    root = _resolve_workspace_root()
    try:
        candidate = Path(project_dir).resolve()
    except (OSError, RuntimeError):
        return None, f"Error: Invalid project_dir '{project_dir}'."
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, f"Error: project_dir '{project_dir}' is outside the workspace root."
    if not candidate.exists() or not candidate.is_dir():
        return None, f"Error: project_dir '{project_dir}' does not exist or is not a directory."
    return candidate, None


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
        # nosec B608 — no untrusted free-text in this query. Every interpolated
        # token is either a dialect-quoted identifier (src/qt via _quote_table,
        # columns via _quote_identifier — both escape embedded quotes), a
        # generated alias (nn{i}/d{i}), or an internal int (sample_rows).
        # Identifiers and COUNT(DISTINCT col) aggregates cannot be bind-parameterized.
        res = await connector.execute(f"SELECT {', '.join(selects)} FROM {src}")  # nosec B608
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


async def _map_explicit_upstreams(connector, schema, work_dir, model_name, upstreams):
    yml_columns = _extract_yml_columns(work_dir, model_name)
    yml_lower = {name.lower() for name in yml_columns}
    out = [f"## Pre-write Column Observations: {model_name}"]
    matched = 0
    source_only = 0
    positional_alignments: list[tuple[str, list[tuple[str, str]]]] = []
    for requested in upstreams:
        if "." not in requested and sum(
            1 for key in schema._raw if key.split(".")[-1].lower() == requested.lower()
        ) > 1:
            out.append(f"### {requested} — AMBIGUOUS; use schema.relation")
            continue
        resolved = schema.resolve(requested)
        if resolved is None:
            out.append(f"### {requested} — NOT FOUND")
            continue
        columns = _get_db_columns(schema, work_dir, resolved)
        profile = await _profile_columns(connector, schema, resolved, columns)
        out.append(f"### {resolved} — {len(columns)} columns")
        for column_name, column_type in columns:
            status = "YML-MATCH" if column_name.lower() in yml_lower else "SOURCE-ONLY"
            matched += status == "YML-MATCH"
            source_only += status == "SOURCE-ONLY"
            stats = profile.get(column_name, {})
            out.append(
                f"  {column_name} ({column_type}) → {status} "
                f"[rows={stats.get('total', 0)}, nulls={stats.get('null_count', 0)}, "
                f"distinct={stats.get('distinct_count', 0)}]"
            )
        if yml_columns and len(columns) == len(yml_columns):
            aligned_pairs = [
                (yml_name, source_name)
                for yml_name, (source_name, _) in zip(yml_columns, columns)
            ]
            pairs = [f"{position}. {yml_name} <- {source_name}"
                     for position, (yml_name, source_name) in enumerate(aligned_pairs, start=1)]
            out.append("  POSITIONAL ALIGNMENT (equal column counts):")
            out.extend(f"    {pair}" for pair in pairs)
            out.append("  This is an ordering observation; project evidence decides whether it is a rename mapping.")
            source_names_lower = {name.lower() for name, _ in columns}
            exact_anchor_count = sum(
                yml_name.lower() in source_names_lower for yml_name in yml_columns
            )
            exact_positions_agree = exact_anchor_count > 0 and all(
                yml_name.lower() == source_name.lower()
                for yml_name, source_name in aligned_pairs
                if yml_name.lower() in source_names_lower
            )
            if exact_positions_agree:
                positional_alignments.append((resolved, aligned_pairs))
        out.append("")
    if len(positional_alignments) == 1:
        relation, pairs = positional_alignments[0]
        candidates = []
        for yml_name, source_name in pairs:
            yml_tokens = yml_name.lower().split("_")
            source_tokens = source_name.lower().split("_")
            shorter, longer = sorted((yml_tokens, source_tokens), key=len)
            boundary_match = any(
                longer[start:start + len(shorter)] == shorter
                for start in (0, len(longer) - len(shorter))
            )
            if boundary_match:
                candidates.append((yml_name, source_name))
        if candidates:
            out.append(f"### POSITIONAL DECORATION CANDIDATES: {relation}")
            out.extend(f"  {yml_name} <- {source_name}" for yml_name, source_name in candidates)
            out.append("These are sole-upstream, equal-width, exact-name-anchored observations; project evidence decides lineage.")
    out.append(f"### Summary: {matched} YML matches, {source_only} source-only observations")
    out.append("These statuses describe availability; project evidence defines output columns.")
    return out


def _observational_mapping(lines: list[str]) -> list[str]:
    observed = []
    matched = 0
    source_only = 0
    for line in lines:
        if line.startswith("### Summary:"):
            continue
        line = line.replace("UNMAPPED-INCLUDE", "SOURCE-ONLY")
        line = line.replace("UNMAPPED-EXCLUDE", "SOURCE-ONLY")
        line = line.replace("MAPPED", "YML-MATCH")
        line = re.sub(r"\[lookup_join_key:[^\]]+\]", "[lookup candidate]", line)
        line = line.replace("[varchar_event_date]", "[date-like VARCHAR]")
        line = line.replace("[varchar_audit_timestamp]", "[timestamp-like VARCHAR]")
        line = line.replace(" — MUST alias", " — shared-name observation")
        if "SKIP these" in line or "Expected minimum columns" in line:
            continue
        matched += line.count("YML-MATCH")
        source_only += line.count("SOURCE-ONLY")
        observed.append(line)
    observed.append(f"### Summary: {matched} YML matches, {source_only} source-only observations")
    return observed


@audited_tool(mcp)
async def map_columns(
    connection_name: str,
    model_name: str,
    project_dir: str,
    exclude: str = "",
    upstream_tables: str = "",
) -> str:
    """Observe upstream columns for a dbt model.

    Use authored SQL lineage when `upstream_tables` is empty. Before SQL has
    lineage, pass up to ten comma-separated unquoted physical relation names.
    Results describe available columns; project evidence defines output columns.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        return f"Error: Invalid model name '{model_name}'."
    work_dir, err = _validated_project_dir(project_dir)
    if err:
        return err
    exclude_set = {c.strip().lower() for c in exclude.split(",") if c.strip()}
    explicit_upstreams = [name.strip() for name in upstream_tables.split(",") if name.strip()]
    if len(explicit_upstreams) > 10:
        return "Error: upstream_tables accepts at most 10 relations."
    for name in explicit_upstreams:
        if not _MODEL_NAME_RE.match(name):
            return f"Error: Invalid unquoted upstream relation '{name}'."

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
            if explicit_upstreams:
                lines = await _map_explicit_upstreams(
                    connector, schema, work_dir, model_name, explicit_upstreams
                )
            else:
                lines = _observational_mapping(
                    await _map_model(connector, schema, work_dir, model_name, exclude_set)
                )
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"
    return "\n".join(lines)


# ── analyze_project_db — the DB half of the old scan_project, one call, any DB ──
_MODEL_PREFIXES = ("stg_", "dim_", "fact_", "int_", "obt_", "fct_", "mart_", "auto_")
# The DB-side hint helpers live in model_map_hints.py.
from gateway.mcp.tools.model_map_hints import (  # noqa: E402
    ScanBudget,
    _driving_table_gaps,
    _staging_gaps,
)

_ANALYSIS_CACHE_TTL_SECONDS = 3600.0
_ANALYSIS_CACHE_MAX = 64
# (org_id, connection, schema fingerprint) -> (monotonic time, report text)
_analysis_cache: dict[tuple[str, str, str], tuple[float, str]] = {}


def _cached_analysis(key: tuple[str, str, str]) -> str | None:
    entry = _analysis_cache.get(key)
    if entry is None:
        return None
    if time.monotonic() - entry[0] > _ANALYSIS_CACHE_TTL_SECONDS:
        _analysis_cache.pop(key, None)
        return None
    return entry[1]


def _remember_analysis(key: tuple[str, str, str], text: str) -> None:
    if len(_analysis_cache) >= _ANALYSIS_CACHE_MAX:
        oldest = min(_analysis_cache, key=lambda k: _analysis_cache[k][0])
        _analysis_cache.pop(oldest, None)
    _analysis_cache[key] = (time.monotonic(), text)


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

    from gateway.connectors.pool_manager import pool_manager
    from gateway.connectors.schema_cache import _schema_fingerprint, schema_cache
    from gateway.governance.context import current_org_id_var
    from gateway.mcp.context import mcp_org_id_var

    # Open the store session only to read the connection record. The introspection
    # and the scans can run for a while; holding a database session open across them
    # left it idle in a transaction until the server closed it.
    try:
        async with _store_session() as store:
            conn_info = await store.get_connection(connection_name)
            if not conn_info:
                return f"Error: Connection '{connection_name}' not found."
            conn_str = await store.get_connection_string(connection_name)
            if not conn_str:
                return "Error: No credentials stored for this connection"
            extras = await store.get_credential_extras(connection_name)
            org_id = current_org_id_var.get(None) or mcp_org_id_var.get(None) or ""
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"

    # schema_cache keys are org scoped, so keep the org var set while using it.
    token = current_org_id_var.set(org_id)
    try:
        raw = schema_cache.get(connection_name)
        async with pool_manager.connection(
            conn_info.db_type, conn_str, credential_extras=extras, connection_name=connection_name
        ) as connector:
            if raw is None:
                raw = await connector.get_schema()
                schema_cache.put(connection_name, raw)
            cache_key = (org_id, connection_name, _schema_fingerprint(raw))
            cached = _cached_analysis(cache_key)
            if cached is not None:
                return cached
            schema = _Schema(raw, conn_info.db_type)
            lookups = _detect_lookups(connector, schema)
            staging = await _staging_gaps(schema)
            driving = await _driving_table_gaps(connector, schema, budget=ScanBudget())
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"
    finally:
        current_org_id_var.reset(token)

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
    report = "\n".join(out)
    _remember_analysis(cache_key, report)
    return report


# -- find_column_producers - which existing models already produce a column ----

def _parse_sql_projections(sql: str) -> list[tuple[str, str]]:
    """Final-SELECT projections as (output_name, expression_text) pairs.

    Same splitting rules as _parse_sql_columns, but keeps the expression so a
    caller can show WHERE a value comes from, not only that it exists.
    """
    clean = re.sub(r"\{\{.*?\}\}", "___REF___", sql)
    clean = re.sub(r"\{%.*?%\}", "", clean)
    clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)
    clean = re.sub(r"--.*$", "", clean, flags=re.MULTILINE)
    matches = list(re.finditer(r"SELECT\s+(.*?)\s+FROM\b", clean, re.IGNORECASE | re.DOTALL))
    if not matches:
        return []
    # Resolve the canonical `select * from <final_cte>` tail into that CTE's
    # own select list (chase up to 5 star hops for nested passthroughs).
    sel = matches[-1]
    sel_text = sel.group(1)
    for _ in range(5):
        if sel_text.strip() != "*" and not re.fullmatch(r"\w+\.\*", sel_text.strip()):
            break
        target_m = re.match(r"\s*([A-Za-z_]\w*)", clean[sel.end():])
        if not target_m:
            return []
        target = target_m.group(1)
        cte_m = re.search(rf"\b{re.escape(target)}\s+as\s*\(", clean, re.IGNORECASE)
        if not cte_m:
            return []
        inner = next((m for m in matches if m.start() > cte_m.end() - 1), None)
        if inner is None or inner is sel:
            return []
        sel = inner
        sel_text = sel.group(1)
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
    projections: list[tuple[str, str]] = []
    for part in parts:
        part = " ".join(part.split())
        if not part or part == "*":
            continue
        as_match = re.search(r"\bAS\s+(\w+)\s*$", part, re.IGNORECASE)
        if as_match:
            projections.append((as_match.group(1), part))
            continue
        words = part.split()
        name = words[-1].split(".")[-1] if words else ""
        if name and name != "___REF___" and name.upper() not in (
            "THEN", "ELSE", "END", "WHEN", "CASE", "AND", "OR", "NOT",
            "NULL", "TRUE", "FALSE", "AS", "FROM", "WHERE", "SELECT",
        ):
            projections.append((name, part))
    return projections


def _direct_relations(sql_text: str) -> list[str]:
    """Physical relations referenced directly in FROM/JOIN (no ref()/source())."""
    clean = re.sub(r"\{\{.*?\}\}", "___REF___", sql_text)
    clean = re.sub(r"--.*$", "", clean, flags=re.MULTILINE)
    hits = re.findall(r"\b(?:FROM|JOIN)\s+((?:[A-Za-z_][\w$]*\.){0,2}[A-Za-z_][\w$]*)",
                      clean, re.IGNORECASE)
    keep: list[str] = []
    for h in hits:
        if h == "___REF___" or h.lower() in ("select", "lateral", "unnest", "values"):
            continue
        keep.append(h)
    return keep


def _column_producers_report(work_dir: Path, columns: list[str], exclude: set[str]) -> list[str]:
    """Pure static scan: which existing model files project each column name."""
    wanted = {c.lower(): c for c in columns}
    out = [f"## Column Producers: {len(columns)} column(s) checked"]
    hits: dict[str, list[str]] = {c.lower(): [] for c in columns}
    cte_names_re = re.compile(r"(?:\bwith\b|,)\s*([A-Za-z_]\w*)\s+as\s*\(", re.IGNORECASE)
    for sql_file in sorted(work_dir.rglob("*.sql")):
        rel = str(sql_file.relative_to(work_dir))
        if any(part in (".claude", "target", "__pycache__") for part in sql_file.parts):
            continue
        is_package = "dbt_packages" in sql_file.parts
        if "macros" in sql_file.parts or rel.startswith("analyses"):
            continue
        model = sql_file.stem
        if model.lower() in exclude:
            continue
        try:
            text = _read_text(sql_file)
        except Exception:
            continue
        projections = _parse_sql_projections(text)
        if not projections:
            continue
        refs = _extract_refs(text)
        sources = [f"{s}.{t}" for s, t in _extract_sources(text)]
        cte_names = {m.group(1).lower() for m in cte_names_re.finditer(text)}
        direct = [d for d in _direct_relations(text) if d.split(".")[-1].lower() not in cte_names]
        reads = ", ".join(
            [f"ref('{r}')" for r in dict.fromkeys(refs)]
            + [f"source('{s}')" for s in dict.fromkeys(sources)]
            + list(dict.fromkeys(direct))
        ) or "(no upstream detected)"
        for name, expr in projections:
            key = name.lower()
            if key in wanted:
                if len(expr) > 140:
                    expr = expr[:140] + "..."
                tag = " [package model]" if is_package else ""
                hits[key].append(f"  {model}{tag} (reads: {reads}) -> {expr}")
    found = 0
    for key, original in wanted.items():
        out.append(f"### {original}")
        if hits[key]:
            found += 1
            out.extend(hits[key][:8])
            if len(hits[key]) > 8:
                out.append(f"  ... and {len(hits[key]) - 8} more")
        else:
            out.append("  no existing model projects this column")
    out.append(f"### Summary: {found} of {len(columns)} column(s) already have a producer")
    out.append("A model that already projects a column is the project's producer for it - "
               "source the value via ref() to that model rather than re-deriving it from a wider relation.")
    return out


@audited_tool(mcp)
async def find_column_producers(
    connection_name: str,
    column_names: str,
    project_dir: str,
    exclude: str = "",
) -> str:
    """Find which existing models already produce given output columns.

    Before writing a model, pass the comma-separated output column names it
    must produce. Scans every model SQL file in the project and reports, per
    column: each existing model whose final SELECT projects a column with that
    name, the relations that model reads (ref()/source()/direct), and the
    projecting expression. Use `exclude` (comma-separated model names) to skip
    the model being written.
    """
    if err := _validate_connection_name(connection_name):
        return f"Error: {err}"
    work_dir, err = _validated_project_dir(project_dir)
    if err:
        return err
    columns = [c.strip() for c in column_names.split(",") if c.strip()]
    if not columns:
        return "Error: column_names cannot be empty. Pass comma-separated output column names."
    if len(columns) > 50:
        return "Error: column_names accepts at most 50 columns per call."
    for c in columns:
        if not re.match(r"^[A-Za-z_][\w$]{0,127}$", c):
            return f"Error: Invalid column name '{c}'."
    exclude_set = {m.strip().lower() for m in exclude.split(",") if m.strip()}
    try:
        return "\n".join(_column_producers_report(work_dir, columns, exclude_set))
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"
