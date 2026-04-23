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
            or "SELECT_REPLACE_THIS_ENTIRE_FILE" in content
            or "-- TODO:" in content
        )
        if is_stub:
            stubs.add(sql_file.stem)
        else:
            complete.add(sql_file.stem)
    return complete, stubs


# ── Macro scanner ─────────────────────────────────────────────────────────

def scan_macros(work_dir: Path) -> list[str]:
    macros_dir = work_dir / "macros"
    if not macros_dir.exists():
        return []
    pat = re.compile(r'\{%-?\s*macro\s+(\w+)\s*\(', re.IGNORECASE)
    names: list[str] = []
    for sql_file in macros_dir.rglob("*.sql"):
        try:
            for line in _read_text(sql_file).splitlines():
                m = pat.search(line)
                if m:
                    names.append(m.group(1))
        except Exception:
            pass
    return sorted(set(names))


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


# ── Package scanner ───────────────────────────────────────────────────────

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

    print("MODELS TO BUILD (defined in YML but no SQL file):")
    print(f"  {', '.join(sorted(missing_models)) if missing_models else 'none'}")
    print()

    print("STUBS TO REWRITE (SQL file exists but is incomplete):")
    print(f"  {', '.join(sorted(stub_models)) if stub_models else 'none'}")
    print()

    print("EXISTING COMPLETE MODELS (do not modify unless needed):")
    print(f"  {', '.join(sorted(materialized)) if materialized else 'none'}")

    if unmaterialized:
        print()
        print("COMPLETE BUT NOT MATERIALIZED (have SQL but no table — run dbt run --select):")
        print(f"  {', '.join(sorted(unmaterialized))}")
    print()

    # Dependencies for models to build/rewrite
    work_models = missing_models | stub_models
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

    # Macros
    macros = scan_macros(work_dir)
    if macros:
        print("AVAILABLE MACROS:")
        for name in macros:
            print(f"  {name}()")
        print()

    # Packages
    pkg_info = scan_packages(work_dir)
    if pkg_info:
        print("PACKAGES:")
        print(f"  {pkg_info}")
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
