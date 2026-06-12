#!/usr/bin/env python3
"""Pre-scan a dbt project and emit a structured context block.

Used by the dbt-workflow SKILL.md via !`python3 scan_project.py` to inject
project state into the skill prompt before Claude starts working.

Scans: YML models, SQL stubs, dependencies, required columns, sources,
macros, current_date hazards, and pre-computed tables (if DuckDB file found).
"""

from __future__ import annotations

import io
import os
import re
import sys
from pathlib import Path

# Force UTF-8 output on Windows (prevents mojibake on em dashes, arrows, etc.)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SKIP_DIRS = (".claude", "dbt_packages", "target", "macros", "__pycache__")


def _read_text(path: Path) -> str:
    """Read a text file, stripping UTF-8 BOM if present."""
    raw = path.read_bytes()
    if raw[:3] == b'\xef\xbb\xbf':
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


# ── YML parsing (no PyYAML dependency — regex-based) ──────────────────────

def _extract_model_names(yml_text: str) -> set[str]:
    names: set[str] = set()
    in_models = False
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("models:") and indent <= 2:
            in_models = True
            continue
        if in_models and indent <= 0 and stripped and not stripped.startswith("#"):
            if not stripped.startswith("-"):
                in_models = False
                continue
        if in_models and 1 <= indent <= 4:
            m = re.match(r'-\s*name:\s*(\S+)', stripped)
            if m:
                names.add(m.group(1))
    return names


def _extract_columns(yml_text: str) -> dict[str, list[str]]:
    """Extract column names per model from YML. Simple regex parser."""
    result: dict[str, list[str]] = {}
    current_model = None
    in_columns = False
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        # Model name
        m = re.match(r'-\s*name:\s*(\S+)', stripped)
        if m and 1 <= indent <= 4:
            current_model = m.group(1)
            in_columns = False
            continue
        if current_model and stripped.startswith("columns:"):
            in_columns = True
            continue
        if in_columns and indent <= 4 and stripped and not stripped.startswith("-"):
            in_columns = False
            continue
        if in_columns:
            cm = re.match(r'-\s*name:\s*(\S+)', stripped)
            if cm:
                result.setdefault(current_model, []).append(cm.group(1))
    return result


def _extract_descriptions(yml_text: str) -> dict[str, str]:
    """Extract model descriptions from YML."""
    result: dict[str, str] = {}
    current_model = None
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        m = re.match(r'-\s*name:\s*(\S+)', stripped)
        if m and 1 <= indent <= 4:
            current_model = m.group(1)
            continue
        if current_model and stripped.startswith("description:"):
            desc = stripped[len("description:"):].strip().strip("'\"")
            if desc:
                result[current_model] = desc[:200].replace("\n", " ")
    return result


def _extract_materializations(yml_text: str) -> dict[str, str]:
    """Extract model materializations from YML config blocks."""
    result: dict[str, str] = {}
    current_model = None
    in_config = False
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        m = re.match(r'-\s*name:\s*(\S+)', stripped)
        if m and 1 <= indent <= 4:
            current_model = m.group(1)
            in_config = False
            continue
        if current_model and stripped.startswith("config:"):
            in_config = True
            continue
        if in_config and indent <= 4 and stripped and not stripped.startswith("materialized"):
            if not stripped.startswith(" ") and not stripped.startswith("-"):
                in_config = False
                continue
        if in_config and current_model:
            mat = re.match(r'materialized:\s*(\S+)', stripped)
            if mat:
                result[current_model] = mat.group(1).strip("'\"")
                in_config = False
    return result


def _extract_sources(yml_text: str) -> list[str]:
    """Extract source definitions from YML."""
    sources: list[str] = []
    in_sources = False
    current_source = None
    in_tables = False
    table_names: list[str] = []
    for line in yml_text.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("sources:"):
            in_sources = True
            continue
        if in_sources and indent <= 0 and stripped and not stripped.startswith("#") and not stripped.startswith("-"):
            # Flush last source
            if current_source and table_names:
                sources.append(f"  source('{current_source}', '<table>') — tables: {', '.join(table_names)}")
            in_sources = False
            continue
        if in_sources:
            m = re.match(r'-\s*name:\s*(\S+)', stripped)
            if m and indent <= 4:
                # Flush previous source
                if current_source and table_names:
                    sources.append(f"  source('{current_source}', '<table>') — tables: {', '.join(table_names)}")
                current_source = m.group(1)
                table_names = []
                in_tables = False
                continue
            if stripped.startswith("tables:"):
                in_tables = True
                continue
            if in_tables:
                tm = re.match(r'-\s*name:\s*(\S+)', stripped)
                if tm:
                    table_names.append(tm.group(1))
    # Flush final
    if current_source and table_names:
        sources.append(f"  source('{current_source}', '<table>') — tables: {', '.join(table_names)}")
    return sources


def _extract_deps_from_sql(work_dir: Path) -> dict[str, list[str]]:
    """Extract ref() dependencies from SQL files."""
    deps: dict[str, list[str]] = {}
    ref_pat = re.compile(r"\{\{\s*ref\(['\"](\w+)['\"]\)\s*\}\}")
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            content = _read_text(sql_file)
            refs = ref_pat.findall(content)
            if refs:
                deps[sql_file.stem] = sorted(set(refs))
        except Exception:
            pass
    return deps


# ── SQL classification ────────────────────────────────────────────────────

def classify_sql_models(work_dir: Path) -> tuple[set[str], set[str]]:
    complete: set[str] = set()
    stubs: set[str] = set()
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            content = _read_text(sql_file).strip()
        except Exception:
            continue
        is_stub = (
            len(content) < 5
            or re.match(r'^select\s+\*\s+from\s+', content, re.IGNORECASE)
            or content.endswith(",")
            or content.endswith("(")
            or (content.count("(") > content.count(")"))
            or re.search(r'(?i)\bREPLACE\b.*\bENTIRE\b.*\bFILE\b', content)
            or re.match(r'^--\s*(TODO|FIXME|PLACEHOLDER)', content, re.IGNORECASE)
        )
        if is_stub:
            stubs.add(sql_file.stem)
        else:
            complete.add(sql_file.stem)
    return complete, stubs


# ── Macro scanner ─────────────────────────────────────────────────────────

def scan_macros(work_dir: Path) -> list[tuple[str, str]]:
    """Return list of (macro_name, full_body) tuples from the macros/ directory."""
    macros_dir = work_dir / "macros"
    if not macros_dir.exists():
        return []
    pat = re.compile(r'\{%-?\s*macro\s+(\w+)\s*\(', re.IGNORECASE)
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for sql_file in macros_dir.rglob("*.sql"):
        try:
            body = _read_text(sql_file).strip()
            for m in pat.finditer(body):
                name = m.group(1)
                if name not in seen:
                    seen.add(name)
                    result.append((name, body))
        except Exception:
            pass
    return sorted(result, key=lambda x: x[0])


# ── current_date scanner ─────────────────────────────────────────────────

def scan_current_date(work_dir: Path) -> list[str]:
    models_dir = work_dir / "models"
    if not models_dir.exists():
        return []
    pat = re.compile(
        r'\bcurrent_date\b|\bnow\(\)|\bcurrent_timestamp\b|\bgetdate\(\)',
        re.IGNORECASE,
    )
    hits: list[str] = []
    for sql_file in models_dir.rglob("*.sql"):
        try:
            for i, line in enumerate(_read_text(sql_file).splitlines(), 1):
                if pat.search(line):
                    rel = str(sql_file.relative_to(work_dir))
                    hits.append(f"  {rel}:{i}: {line.strip()}")
        except Exception:
            pass
    return hits


def detect_lookup_joins(work_dir: Path) -> list[str]:
    """Detect _id/_ids columns that have matching lookup tables in the DB."""
    hints: list[str] = []
    for db_file in work_dir.glob("*.duckdb"):
        try:
            import duckdb
            conn = duckdb.connect(str(db_file), read_only=True)
            all_tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
            for tbl in sorted(all_tables):
                cols = conn.execute(f'DESCRIBE "{tbl}"').fetchall()
                for col_name, col_type, *_ in cols:
                    low = col_name.lower()
                    if low.endswith("_ids"):
                        prefix = low[:-4]
                    elif low.endswith("_id") and low != "id":
                        prefix = low[:-3]
                    else:
                        continue
                    for candidate in all_tables:
                        cl = candidate.lower()
                        if cl in (f"{prefix}s", f"stg_{prefix}s", f"{prefix}",
                                  f"stg_{prefix}", f"dim_{prefix}s", f"dim_{prefix}"):
                            if candidate == tbl:
                                continue
                            lk_cols = [r[0] for r in conn.execute(f'DESCRIBE "{candidate}"').fetchall()]
                            name_cols = [c for c in lk_cols if "name" in c.lower() or "company" in c.lower()]
                            if name_cols:
                                hints.append(
                                    f"  {tbl}.{col_name} → JOIN {candidate} → use {name_cols[0]}"
                                )
                            break
            conn.close()
        except Exception:
            pass
        break
    return hints


def detect_parent_child_gaps(work_dir: Path) -> list[str]:
    """Detect parent-child table pairs where some parents have NO children.

    When aggregating child records by parent ID, the parent table must be
    the FROM clause to preserve parents with zero children.
    """
    hints: list[str] = []
    try:
        import duckdb
    except ImportError:
        return hints

    for db_file in work_dir.glob("*.duckdb"):
        try:
            con = duckdb.connect(str(db_file), read_only=True)
            all_tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            table_cols: dict[str, list[str]] = {}
            for t in all_tables:
                try:
                    table_cols[t] = [r[0] for r in con.execute(f'DESCRIBE "{t}"').fetchall()]
                except Exception:
                    pass

            # Find parent-child pairs by checking every _id column in every
            # child table against every parent table's `id` column.
            # No name-matching heuristics — test actual key overlap in the DB.
            parents_with_id: dict[str, str] = {}  # table -> id col name
            for t in all_tables:
                for c in table_cols.get(t, []):
                    if c.lower() == "id":
                        parents_with_id[t] = c
                        break

            checked: set[tuple[str, str]] = set()
            for child in all_tables:
                c_cols = table_cols.get(child, [])
                fk_cols = [c for c in c_cols if c.lower().endswith("_id")
                           and c.lower() != "id"]
                for fk_col in fk_cols:
                    for parent, p_id in parents_with_id.items():
                        if parent == child:
                            continue
                        pair = (parent, child, fk_col)
                        if pair in checked:
                            continue
                        checked.add(pair)
                        # Quick entity-name plausibility check: the FK prefix
                        # should appear somewhere in the parent table name to
                        # avoid testing every combination (N^2 queries).
                        fk_prefix = fk_col.lower().replace("_id", "")
                        if fk_prefix not in parent.lower():
                            continue
                        try:
                            p_count = con.execute(
                                f'SELECT COUNT(DISTINCT "{p_id}") FROM "{parent}"'
                            ).fetchone()[0]
                            if p_count == 0:
                                continue
                            overlap = con.execute(
                                f'SELECT COUNT(*) FROM '
                                f'(SELECT DISTINCT "{p_id}" FROM "{parent}") p '
                                f'JOIN (SELECT DISTINCT "{fk_col}" FROM "{child}") c '
                                f'ON p."{p_id}" = c."{fk_col}"'
                            ).fetchone()[0]
                            orphans = p_count - overlap
                            if orphans > 0:
                                hints.append(
                                    f"  {parent}.{p_id} ↔ {child}.{fk_col}: "
                                    f"{orphans} of {p_count} parent rows have NO children. "
                                    f"Drive FROM {parent} LEFT JOIN {child} to keep them."
                                )
                        except Exception:
                            pass
            con.close()
        except Exception:
            pass
        break
    return hints


def detect_staging_gaps(work_dir: Path) -> list[str]:
    """Detect where staging models filter rows from raw sources."""
    hints: list[str] = []
    try:
        import duckdb
    except ImportError:
        return hints

    for db_file in work_dir.glob("*.duckdb"):
        try:
            con = duckdb.connect(str(db_file), read_only=True)
            all_tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            for tbl in sorted(all_tables):
                if not tbl.startswith("stg_"):
                    continue
                # Find the raw table this staging model wraps
                raw_name = tbl.replace("stg_", "").rstrip("s")
                raw_match = None
                for candidate in all_tables:
                    if candidate.lower() in (raw_name, raw_name + "s",
                                              tbl.replace("stg_", "")):
                        raw_match = candidate
                        break
                if not raw_match:
                    continue
                try:
                    stg_count = con.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                    raw_count = con.execute(f'SELECT COUNT(*) FROM "{raw_match}"').fetchone()[0]
                    if stg_count < raw_count:
                        diff = raw_count - stg_count
                        hints.append(
                            f"  {tbl}: {stg_count} rows (raw {raw_match}: {raw_count} — "
                            f"staging filters {diff} rows). Use ref('{tbl}') not source()."
                        )
                except Exception:
                    pass
            con.close()
        except Exception:
            pass
        break
    return hints


# ── DuckDB table detection ───────────────────────────────────────────────

def detect_db_tables(work_dir: Path) -> set[str]:
    """Find tables in the project's DuckDB file (if any)."""
    tables: set[str] = set()
    # Look for .duckdb files in the project directory
    for db_file in work_dir.glob("*.duckdb"):
        try:
            import duckdb
            conn = duckdb.connect(str(db_file), read_only=True)
            result = conn.execute("SHOW TABLES").fetchall()
            tables.update(row[0] for row in result)
            conn.close()
        except Exception:
            pass
        break  # Only check the first one
    return tables


def detect_aggregation_driving_table(work_dir: Path) -> list[str]:
    """Detect parent-child source table pairs and emit driving-table hints.

    When a model aggregates a child table (e.g. conversation_parts) by a parent
    table's primary key (e.g. conversation_id), the correct pattern is:
      FROM parent LEFT JOIN child ... GROUP BY parent.pk
    This ensures parent rows with zero children still appear (count = 0).

    Detection: find DB table pairs where table A has column "id" and table B has
    a foreign key "<entity>_id" pointing to A, and the child table name contains
    the parent entity (e.g. conversation_part vs conversation).

    Only emits hints for pairs where some parent rows have no matching children,
    because that is when the driving-table choice affects correctness.
    """
    hints: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()

    for db_file in work_dir.glob("*.duckdb"):
        try:
            import duckdb
            conn = duckdb.connect(str(db_file), read_only=True)
            all_tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}

            # Gather column sets for every DB table
            table_cols: dict[str, list[str]] = {}
            for tbl in all_tables:
                try:
                    cols = [r[0] for r in conn.execute(f'DESCRIBE "{tbl}"').fetchall()]
                    table_cols[tbl] = cols
                except Exception:
                    pass

            # Find parent-child pairs:
            # Parent has "id"; child has "<entity>_id" where entity derives from
            # the parent table name (minus suffixes like _data, _history).
            for parent_tbl, parent_cols in table_cols.items():
                p_cols_lower = {c.lower() for c in parent_cols}
                if "id" not in p_cols_lower:
                    continue

                # Derive entity name: "conversation_history_data" -> "conversation"
                p_name = parent_tbl.lower()
                for suffix in ("_history_data", "_data", "_history"):
                    if p_name.endswith(suffix):
                        entity = p_name[: -len(suffix)]
                        break
                else:
                    entity = p_name

                if not entity or len(entity) < 3:
                    continue

                fk_col = f"{entity}_id"

                for child_tbl, child_cols in table_cols.items():
                    if child_tbl == parent_tbl:
                        continue
                    # Child table name must contain the parent entity to be a
                    # true parent-child relationship (not just a random FK match)
                    if entity not in child_tbl.lower():
                        continue
                    c_cols_lower = {c.lower() for c in child_cols}
                    if fk_col not in c_cols_lower:
                        continue

                    pair_key = (parent_tbl, child_tbl)
                    if pair_key in seen_pairs:
                        continue
                    seen_pairs.add(pair_key)

                    # Only emit hint if some parent rows have no matching children.
                    # That is when driving FROM parent (LEFT JOIN child) vs
                    # FROM child produces different row counts.
                    try:
                        orphan_count = conn.execute(
                            f'SELECT COUNT(*) FROM "{parent_tbl}" p '
                            f'LEFT JOIN "{child_tbl}" c ON p.id = c."{fk_col}" '
                            f"WHERE c.\"{fk_col}\" IS NULL"
                        ).fetchone()[0]
                    except Exception:
                        orphan_count = 0

                    if orphan_count > 0:
                        try:
                            p_count = conn.execute(
                                f'SELECT COUNT(*) FROM "{parent_tbl}"'
                            ).fetchone()[0]
                        except Exception:
                            p_count = 0
                        hints.append(
                            f"  {parent_tbl}.id = {child_tbl}.{fk_col}: "
                            f"{orphan_count} of {p_count} parent rows have NO children. "
                            f"Decide the output grain: if childless {parent_tbl} rows "
                            f"belong in the output, drive FROM {parent_tbl} LEFT JOIN "
                            f"{child_tbl} (their metrics are 0/NULL). If the model only "
                            f"covers {parent_tbl} rows that HAVE {child_tbl} activity, "
                            f"drive FROM {child_tbl} and INNER JOIN {parent_tbl}."
                        )

            conn.close()
        except Exception:
            pass
        break  # Only check the first one

    # Cap output to avoid overwhelming the agent with low-value hints.
    # Sort by orphan ratio descending so the most important pairs appear first.
    if len(hints) > 5:
        hints = hints[:5]
        hints.append("  (showing top 5 — run DESCRIBE on source tables to find more)")

    return hints


# ── Package scanner ───────────────────────────────────────────────────────

def _find_sibling_patterns(
    work_dir: Path,
    work_models: set[str],
    complete_models: set[str],
    all_columns: dict[str, list[str]],
) -> dict[str, list[tuple[str, int]]]:
    """For each stub/missing model, find complete siblings in the same directory."""
    sql_dirs: dict[str, Path] = {}
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        sql_dirs[sql_file.stem] = sql_file.parent

    result: dict[str, list[tuple[str, int]]] = {}
    for model in sorted(work_models):
        target_dir = sql_dirs.get(model)
        if not target_dir:
            continue
        siblings = []
        for sql_file in target_dir.glob("*.sql"):
            sib = sql_file.stem
            if sib == model or sib not in complete_models:
                continue
            cols = all_columns.get(sib, [])
            siblings.append((sib, len(cols) if cols else 0))
        if siblings:
            result[model] = siblings
    return result


def scan_packages(work_dir: Path) -> str:
    if not (work_dir / "packages.yml").exists():
        return ""
    lines: list[str] = []
    pkg_dir = work_dir / "dbt_packages"
    if pkg_dir.exists():
        pkg_models: list[str] = []
        for sql_file in pkg_dir.rglob("*.sql"):
            if sql_file.stem.startswith("stg_") or sql_file.stem.startswith("int_"):
                pkg_models.append(sql_file.stem)
        if pkg_models:
            lines.append(f"Package staging/intermediate models available: {', '.join(sorted(set(pkg_models))[:20])}")

    # Check for dbt.* namespace usage in existing SQL
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in SKIP_DIRS):
            continue
        try:
            if "dbt." in _read_text(sql_file):
                lines.append("dbt.* cross-adapter macros ARE available: dbt.date_trunc(), dbt.length(), dbt.replace(), etc.")
                break
        except Exception:
            pass
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    # Find the dbt project directory
    work_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()

    # Look for dbt_project.yml to confirm we're in a dbt project
    if not (work_dir / "dbt_project.yml").exists():
        # Try common subdirectories
        for subdir in work_dir.iterdir():
            if subdir.is_dir() and (subdir / "dbt_project.yml").exists():
                work_dir = subdir
                break
        else:
            print("(no dbt_project.yml found — skip project scan)")
            return

    # Scan YML
    yml_models: set[str] = set()
    all_columns: dict[str, list[str]] = {}
    all_descriptions: dict[str, str] = {}
    all_materializations: dict[str, str] = {}
    all_sources: list[str] = []

    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in SKIP_DIRS):
                continue
            try:
                text = _read_text(yml_file)
                yml_models.update(_extract_model_names(text))
                all_columns.update(_extract_columns(text))
                all_descriptions.update(_extract_descriptions(text))
                all_materializations.update(_extract_materializations(text))
                all_sources.extend(_extract_sources(text))
            except Exception:
                pass

    # Classify SQL
    complete_models, stub_models = classify_sql_models(work_dir)
    sql_models = complete_models | stub_models
    missing_models = yml_models - sql_models

    # Database tables
    db_tables = detect_db_tables(work_dir)
    materialized = (yml_models & complete_models) & db_tables
    unmaterialized = (yml_models & complete_models) - db_tables

    # Dependencies
    deps = _extract_deps_from_sql(work_dir)

    # Packages
    has_packages = (work_dir / "packages.yml").exists()

    # ── Output ────────────────────────────────────────────────────────────

    print(f"## dbt Project Scan: {work_dir.name}")
    print()

    if has_packages:
        print("Run `dbt deps` first — this project has a packages.yml.")
    else:
        print("Do NOT run `dbt deps` — packages are pre-installed.")
    print()

    print("MODELS TO BUILD (defined in YML but no SQL file — create EXACT filenames):")
    if missing_models:
        for m in sorted(missing_models):
            mat = all_materializations.get(m, "table")
            # Find which YML file defines this model and list sibling models
            yml_file = ""
            siblings_in_yml = []
            for yf in (work_dir / "models").rglob("*.yml"):
                if "dbt_packages" in str(yf):
                    continue
                try:
                    import yaml
                    with open(yf) as f:
                        data = yaml.safe_load(f)
                    if data and "models" in data:
                        names = [md.get("name", "") for md in data["models"]]
                        if m in names:
                            yml_file = str(yf.relative_to(work_dir))
                            siblings_in_yml = [n for n in names if n != m]
                except Exception:
                    pass
            sib_str = f"  siblings: {', '.join(siblings_in_yml)}" if siblings_in_yml else ""
            yml_str = f"  YML: {yml_file}" if yml_file else ""
            print(f"  → {m}.sql  (materialized={mat}){yml_str}")
            if sib_str:
                print(f"    Read sibling YML descriptions for column vocabulary hints")
    else:
        print("  none")
    print()

    # Detect var() reference conventions from dbt_project.yml
    dbt_project_yml = work_dir / "dbt_project.yml"
    if dbt_project_yml.exists():
        try:
            import yaml
            with open(dbt_project_yml) as f:
                proj_cfg = yaml.safe_load(f) or {}
            all_vars = proj_cfg.get("vars", {})
            var_refs: list[str] = []
            for section_key, section_val in all_vars.items():
                if isinstance(section_val, dict):
                    for var_name, var_val in section_val.items():
                        if isinstance(var_val, str) and "ref(" in var_val:
                            var_refs.append(
                                f"  var('{var_name}') → {var_val}"
                            )
            if var_refs:
                print("VAR ALIASES (use var() instead of ref() in new models — project convention):")
                for vr in var_refs:
                    print(vr)
                print()
        except Exception:
            pass

    # Aggregation driving table — print EARLY so agent sees it before writing any SQL
    agg_patterns = detect_aggregation_driving_table(work_dir)
    if agg_patterns:
        print("AGGREGATION DRIVING TABLE (which source table to use as FROM clause):")
        print("\n".join(agg_patterns))
        print()

    print("STUBS TO REWRITE (SQL file exists but is incomplete):")
    print(f"  {', '.join(sorted(stub_models)) if stub_models else 'none'}")
    print()

    print("EXISTING COMPLETE MODELS (ALREADY DONE — skip to Step 8 for these):")
    print(f"  {', '.join(sorted(materialized)) if materialized else 'none'}")
    if materialized:
        print("  ⚠ These SQL files already exist and compile. Do NOT delete or recreate them.")

    if unmaterialized:
        print()
        print("COMPLETE BUT NOT MATERIALIZED (have SQL but no table — run dbt run --select):")
        print(f"  {', '.join(sorted(unmaterialized))}")

    # Orphan SQL files (SQL exists but no YML model)
    orphans = sql_models - yml_models
    if orphans:
        print()
        print("SQL FILES WITHOUT YML (usable as ref() targets — prefer ref() over source()):")
        for o in sorted(orphans):
            if missing_models:
                for m in sorted(missing_models):
                    if o in m or m in o or (len(o) > 5 and o[:5] == m[:5]):
                        print(f"  {o}.sql — possible match: {m} (defined in YML)")
                        break
                else:
                    print(f"  {o}.sql — no YML definition found")
            else:
                print(f"  {o}.sql — no YML definition found")
    print()

    # Sibling patterns for ALL yml models (helps with column conventions)
    all_work = yml_models  # Show siblings for every model, not just stubs/missing
    sibling_info = _find_sibling_patterns(work_dir, all_work, complete_models | stub_models, all_columns)
    if sibling_info:
        print("SIBLING PATTERNS (complete models in same directory — read for column conventions):")
        for model, siblings in sorted(sibling_info.items()):
            sib_strs = [f"{s} ({c} cols)" if c else f"{s} (? cols)" for s, c in siblings]
            print(f"  {model}: {', '.join(sib_strs)}")
        print()

    # Reverse dependencies — models that ref() other models
    work_models = missing_models | stub_models
    reverse_deps: dict[str, list[str]] = {}
    for src_model, ref_list in deps.items():
        for ref_name in ref_list:
            if ref_name in yml_models and src_model != ref_name:
                reverse_deps.setdefault(ref_name, []).append(src_model)
    if reverse_deps:
        print("REFERENCING MODELS (models that ref() these — read for column conventions):")
        for model, consumers in sorted(reverse_deps.items()):
            print(f"  {model} is referenced by: {', '.join(sorted(consumers))}")
        print()

    # Dependencies for models to build/rewrite
    dep_lines = []
    for model in sorted(work_models):
        if model in deps:
            dep_lines.append(f"  {model} depends on: {', '.join(deps[model])}")
    if dep_lines:
        print("DEPENDENCIES (build in this order):")
        print("\n".join(dep_lines))
    else:
        print("DEPENDENCIES: (check YML refs and existing SQL for dependency info)")
    print()

    # Required columns
    col_lines = []
    for model in sorted(work_models):
        desc = all_descriptions.get(model, "")
        desc_str = f" | DESC: {desc}" if desc else ""
        if model in all_columns:
            col_lines.append(f"  {model}: {', '.join(all_columns[model])}{desc_str}")
    if col_lines:
        print("REQUIRED COLUMNS (must match exactly — missing columns = guaranteed fail):")
        print("\n".join(col_lines))
    else:
        print("REQUIRED COLUMNS: (read YML files for column specs)")
    print()

    # Sources
    if all_sources:
        print("AVAILABLE SOURCES:")
        print("\n".join(all_sources))
        print()

    # Macros — include full definitions so the agent knows what they do
    macros = scan_macros(work_dir)
    if macros:
        print("AVAILABLE MACROS (use these in your models — they exist for a reason):")
        for name, body in macros:
            print(f"\n  ### {name}")
            for line in body.splitlines():
                print(f"  {line}")
        print()

    # Packages
    pkg_info = scan_packages(work_dir)
    if pkg_info:
        print("PACKAGES:")
        print(f"  {pkg_info}")
        print()

    # Snapshot detection
    snapshots_dir = work_dir / "snapshots"
    if snapshots_dir.exists():
        snap_files = list(snapshots_dir.rglob("*.sql"))
        print(f"SNAPSHOTS DIRECTORY: {len(snap_files)} snapshot file(s) in snapshots/")
        print("  Load `/signalpilot-dbt:dbt-snapshots` skill. Run DESCRIBE on source tables for exact column casing.")
        print()

    # Parent-child gap detection
    pc_hints = detect_parent_child_gaps(work_dir)
    if pc_hints:
        print("AGGREGATION DRIVING TABLE (parent rows with NO children — drive FROM parent):")
        print("\n".join(pc_hints))
        print()

    # Staging vs raw row count gaps
    staging_hints = detect_staging_gaps(work_dir)
    if staging_hints:
        print("STAGING FILTERS (staging models have fewer rows than raw — use ref() not source()):")
        print("\n".join(staging_hints))
        print()

    # Lookup join hints (from DB analysis)
    lookup_hints = detect_lookup_joins(work_dir)
    if lookup_hints:
        print("LOOKUP JOINS AVAILABLE (_id columns with matching dimension tables — resolve to display names):")
        print("\n".join(lookup_hints))
        print()

    # current_date warnings
    cd_hits = scan_current_date(work_dir)
    if cd_hits:
        print("WARNING — FILES USING current_date (must fix with fix_date_spine_hazards):")
        print("\n".join(cd_hits))
        print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"(project scan error: {e})")
