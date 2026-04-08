"""
Spider2-DBT benchmark runner — runs directly without Docker.

Uses the Claude CLI (not SDK) with MCP config for SignalPilot integration.
Intended for use inside a container or machine that already has all deps
(dbt-duckdb, claude CLI, python gateway) installed.

Usage:
    python -m benchmark.run_direct chinook001
    python -m benchmark.run_direct chinook001 --model claude-opus-4-6
    python -m benchmark.run_direct chinook001 --skip-agent   # re-eval only
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Paths ──────────────────────────────────────────────────────────────────────
SPIDER2_DBT_DIR = Path(
    os.environ.get("SPIDER2_DBT_DIR", os.path.expanduser("~/spider2-repo/spider2-dbt"))
)
EXAMPLES_DIR = SPIDER2_DBT_DIR / "examples"
GOLD_DIR = SPIDER2_DBT_DIR / "evaluation_suite" / "gold"
EVAL_JSONL = GOLD_DIR / "spider2_eval.jsonl"

BENCHMARK_DIR = Path(__file__).resolve().parent
WORK_DIR = BENCHMARK_DIR / "_dbt_workdir"
SKILLS_SRC = BENCHMARK_DIR / "skills"
GATEWAY_SRC = PROJECT_ROOT / "signalpilot" / "gateway"
MCP_CONFIG = BENCHMARK_DIR / "mcp_test_config.json"

TASK_JSONL = EXAMPLES_DIR / "spider2-dbt.jsonl"


# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO") -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def log_separator(title: str = "") -> None:
    print(f"\n{'='*60}", flush=True)
    if title:
        print(f"  {title}", flush=True)
        print(f"{'='*60}", flush=True)


# ── Task loading ───────────────────────────────────────────────────────────────

def load_task(instance_id: str) -> dict:
    """Load task definition from the JSONL file."""
    with open(TASK_JSONL) as f:
        for line in f:
            task = json.loads(line.strip())
            if task["instance_id"] == instance_id:
                return task
    raise ValueError(f"Task '{instance_id}' not found in {TASK_JSONL}")


def load_eval_config(instance_id: str) -> dict | None:
    """Load evaluation config for this task from spider2_eval.jsonl."""
    with open(EVAL_JSONL) as f:
        for line in f:
            entry = json.loads(line.strip())
            if entry["instance_id"] == instance_id:
                return entry
    return None


# ── Workdir setup ──────────────────────────────────────────────────────────────

def _force_rmtree(path: Path) -> None:
    """Remove directory tree, handling permission errors."""
    import stat

    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)

    shutil.rmtree(path, onerror=on_error)


def prepare_workdir(instance_id: str) -> Path:
    """Copy task's dbt project to a fresh working directory."""
    src = EXAMPLES_DIR / instance_id
    dst = WORK_DIR / instance_id
    if dst.exists():
        _force_rmtree(dst)
    shutil.copytree(src, dst)
    log(f"Copied task files: {src} -> {dst}")

    # Copy skills into .claude/skills/ so Claude Code loads them natively
    skills_dst = dst / ".claude" / "skills"
    if SKILLS_SRC.exists():
        shutil.copytree(
            SKILLS_SRC,
            skills_dst,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("*.json", "__pycache__"),
        )
        skill_count = len(list(skills_dst.rglob("SKILL.md")))
        log(f"Copied {skill_count} skills -> {skills_dst}")
    else:
        log(f"Skills directory not found: {SKILLS_SRC}", "WARN")

    return dst


def write_claude_md(work_dir: Path, instance_id: str, instruction: str) -> None:
    """Write CLAUDE.md with key task instructions into the work directory."""
    duckdb_files = list(work_dir.glob("*.duckdb"))
    db_path = str(duckdb_files[0]) if duckdb_files else "<not found>"

    content = f"""# Spider2-DBT Benchmark Task: {instance_id}

## Your Task
{instruction}

## Database Access
The DuckDB database is registered in SignalPilot as connection `{instance_id}`.
Local path: `{db_path}`

Use SignalPilot MCP tools to explore and query the database:
- `mcp__signalpilot__list_tables` — list all tables
- `mcp__signalpilot__describe_table` — column details for a table
- `mcp__signalpilot__explore_table` — deep-dive with sample values
- `mcp__signalpilot__query_database` — run SQL queries (read-only)
- `mcp__signalpilot__schema_overview` — quick overview of the whole database
- `mcp__signalpilot__schema_ddl` — full schema as DDL (CREATE TABLE statements)
- `mcp__signalpilot__schema_link` — find tables relevant to a question
- `mcp__signalpilot__find_join_path` — find how to join two tables
- `mcp__signalpilot__explore_column` — distinct values for a column
- `mcp__signalpilot__validate_sql` — check SQL syntax without executing
- `mcp__signalpilot__debug_cte_query` — test CTE steps independently
- `mcp__signalpilot__explain_query` — get execution plan

## Instructions
1. {'Run `dbt deps` once at the start.' if (work_dir / 'packages.yml').exists() else 'Do NOT run `dbt deps` — this project has no packages.yml and packages are pre-installed.'}
2. Use `list_tables` (shows row counts, PKs, FKs) then `explore_table` on key source tables (shows sample data).
3. Read existing YAML files to find model definitions that are missing .sql files.
4. Write each missing .sql file using DuckDB-compatible SQL with dbt ref()/source() macros.
5. Do NOT modify .yml files.
6. Run `dbt run --select model_name` to validate each model as you write it.
7. Use `validate_sql` to check syntax before writing, `dbt compile` to verify before `dbt run`.
8. If dbt run fails, read the error, fix the SQL, and re-run.
9. Use DuckDB SQL syntax (not PostgreSQL, not MySQL).
"""
    (work_dir / "CLAUDE.md").write_text(content)
    log(f"Wrote CLAUDE.md to {work_dir}")


# ── SignalPilot connection registration ────────────────────────────────────────

def register_local_connection(instance_id: str, db_path: str) -> bool:
    """Register the task's DuckDB in the local SignalPilot store (~/.signalpilot/connections.json).

    Always deletes and re-creates to ensure the path matches the current workdir.
    """
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.store import create_connection, delete_connection, get_connection
        from gateway.models import ConnectionCreate, DBType

        existing = get_connection(instance_id)
        if existing:
            delete_connection(instance_id)
            log(f"Deleted stale connection '{instance_id}'")

        create_connection(
            ConnectionCreate(
                name=instance_id,
                db_type=DBType.duckdb,
                database=db_path,
                description=f"Spider2-DBT benchmark: {instance_id}",
            )
        )
        log(f"Registered connection '{instance_id}' -> {db_path}")
        return True
    except Exception as e:
        log(f"Failed to register local connection: {e}", "WARN")
        return False


# ── Agent prompt ───────────────────────────────────────────────────────────────

def _extract_model_names(yml_content: str) -> set[str]:
    """Extract top-level model names from a dbt YAML file.

    Only picks up names directly under 'models:' (indented 2 spaces),
    not column names (indented 6+ spaces) or source table names.
    """
    names: set[str] = set()
    in_models_block = False
    for line in yml_content.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        # Detect top-level 'models:' key
        if stripped.startswith("models:") and indent <= 2:
            in_models_block = True
            continue
        # Exit models block on another top-level key
        if in_models_block and indent <= 0 and stripped and not stripped.startswith("#"):
            if not stripped.startswith("-"):
                in_models_block = False
                continue
        # Match '  - name: xxx' (indent 2-4, model-level entries)
        if in_models_block and 1 <= indent <= 4:
            m = re.match(r'-\s*name:\s*(\S+)', stripped)
            if m:
                names.add(m.group(1))
    return names


def _scan_yml_models(work_dir: Path) -> set[str]:
    """Extract model names from all .yml and .yaml files in the work directory."""
    yml_models: set[str] = set()
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                yml_models.update(_extract_model_names(yml_file.read_text()))
            except Exception:
                pass
    return yml_models


def _classify_sql_models(work_dir: Path) -> tuple[set[str], set[str]]:
    """Return (complete_models, stub_models).

    A file is a stub/incomplete if it is 0 bytes, its entire content is a
    single ``select * from ...`` line, or it ends with a trailing comma
    (truncated CTE).
    """
    complete: set[str] = set()
    stubs: set[str] = set()
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in (".claude", "dbt_packages", "target", "macros")):
            continue
        content = sql_file.read_text().strip()
        is_stub = (
            len(content) < 5
            or re.match(r'^select\s+\*\s+from\s+', content, re.IGNORECASE)
            or content.endswith(",")  # truncated CTE
            or content.endswith("(")  # truncated subquery
            or (content.count("(") > content.count(")"))  # unbalanced parens
        )
        if is_stub:
            stubs.add(sql_file.stem)
        else:
            complete.add(sql_file.stem)
    return complete, stubs


def _create_sql_templates(work_dir: Path, eval_critical_models: set[str]) -> list[str]:
    """Pre-populate starter SQL files for eval-critical models with no existing SQL file.

    Only creates files for models with no SQL file at all — does not overwrite
    stubs or complete models. Returns a list of model names for which templates
    were created.
    """
    complete_sql_models, stub_sql_models = _classify_sql_models(work_dir)
    column_map = _extract_model_columns(work_dir)
    already_have_sql = complete_sql_models | stub_sql_models

    models_dir = work_dir / "models"
    target_dir = models_dir if models_dir.exists() else work_dir

    created: list[str] = []
    for model_name in eval_critical_models:
        if model_name in already_have_sql:
            continue
        try:
            columns = column_map.get(model_name, [])
            col_comment = ", ".join(columns) if columns else "(check schema.yml)"
            # Template must NOT compile — forces agent to rewrite the entire file
            template = (
                "{{ config(materialized='table') }}\n\n"
                f"-- REQUIRED OUTPUT COLUMNS: {col_comment}\n"
                "-- TODO: Write the complete SQL query for this model.\n"
                "-- Explore source tables with SignalPilot tools before writing.\n"
                "-- This file intentionally fails compilation until you replace it.\n"
                "SELECT_REPLACE_THIS_ENTIRE_FILE\n"
            )
            sql_path = target_dir / f"{model_name}.sql"
            sql_path.write_text(template)
            created.append(model_name)
        except Exception as exc:
            log(f"Warning: could not create SQL template for {model_name!r}: {exc}", "WARN")

    if created:
        log(f"Created {len(created)} SQL template(s): {sorted(created)}")
    return created


def _create_ephemeral_stubs(work_dir: Path) -> list[str]:
    """Auto-create ephemeral stub SQL files for ref() targets that are raw DuckDB tables.

    Scans all .sql files under models/ for {{ ref('...') }} calls, then for any
    ref target that has no corresponding .sql file but does exist as a raw DuckDB
    table, writes a minimal ephemeral stub so dbt compilation succeeds without
    wasting agent turns on avoidable errors.

    Returns list of model names for which stubs were created.
    """
    skip_dirs = (".claude", "dbt_packages", "target", "macros")

    # Step 1: Collect all existing .sql file stems (the already-resolved models).
    existing_sql_stems: set[str] = set()
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in skip_dirs):
            continue
        existing_sql_stems.add(sql_file.stem)

    # Step 2: Scan models/ for {{ ref('name') }} and {{ ref("name") }} patterns.
    ref_pattern = re.compile(r'\{\{\s*ref\(\s*[\'\"]([\w]+)[\'\"]\s*\)\s*\}\}')
    ref_targets: set[str] = set()
    models_dir = work_dir / "models"
    scan_root = models_dir if models_dir.exists() else work_dir
    for sql_file in scan_root.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in skip_dirs):
            continue
        try:
            content = sql_file.read_text()
            ref_targets.update(ref_pattern.findall(content))
        except Exception:
            pass

    # Step 3: Compute unresolved ref targets.
    unresolved = ref_targets - existing_sql_stems

    if not unresolved:
        return []

    # Step 5: Get raw DuckDB table names for O(1) lookup.
    duckdb_tables: set[str] = set(_detect_precomputed_tables(work_dir))

    # Step 6: Write ephemeral stubs for unresolved refs that exist as DuckDB tables.
    target_dir = models_dir if models_dir.exists() else work_dir
    created: list[str] = []
    for name in unresolved:
        if name not in duckdb_tables:
            continue
        target_path = target_dir / f"{name}.sql"
        if target_path.exists():
            continue
        stub_content = "{{ config(materialized='ephemeral') }}\n" + f"select * from main.{name}\n"
        try:
            target_path.write_text(stub_content)
            created.append(name)
        except Exception as exc:
            log(f"Warning: could not create ephemeral stub for {name!r}: {exc}", "WARN")

    return created


def _extract_model_deps(work_dir: Path) -> dict[str, list[str]]:
    """Extract model dependency info (refs) from YML files."""
    import yaml

    deps: dict[str, list[str]] = {}
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "models" in data:
                    for model in data["models"]:
                        name = model.get("name")
                        refs = model.get("refs", [])
                        if name and refs:
                            deps[name] = [r["name"] if isinstance(r, dict) else str(r) for r in refs]
            except Exception:
                pass
    return deps


def _extract_model_columns(work_dir: Path) -> dict[str, list[str]]:
    """Extract column names from YML model definitions."""
    import yaml

    result: dict[str, list[str]] = {}
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "models" in data:
                    for model in data["models"]:
                        name = model.get("name")
                        columns = model.get("columns", [])
                        if name and columns:
                            result[name] = [c["name"] for c in columns if "name" in c]
            except Exception:
                pass
    return result


def _scan_macros(work_dir: Path) -> dict[str, str]:
    """Find macro names in macros/ dir by parsing {% macro name(...) %} patterns.

    Returns {macro_name: signature_line} for all macros found.
    Skips dbt_packages/, .claude/, and target/ subdirectories.
    """
    macros_dir = work_dir / "macros"
    if not macros_dir.exists():
        return {}

    macro_pattern = re.compile(r'\{%-?\s*macro\s+(\w+)\s*\(', re.IGNORECASE)
    result: dict[str, str] = {}

    for sql_file in macros_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in ("dbt_packages", ".claude", "target")):
            continue
        try:
            content = sql_file.read_text()
            for line in content.splitlines():
                m = macro_pattern.search(line)
                if m:
                    macro_name = m.group(1)
                    result[macro_name] = line.strip()
        except Exception:
            pass

    return result


def _detect_precomputed_tables(work_dir: Path) -> list[str]:
    """Open the task's .duckdb file and list all tables already present.

    Returns list of table names, or empty list if DB is missing/locked.
    """
    try:
        import duckdb
    except ImportError:
        return []

    db_candidates = list(work_dir.glob("*.duckdb"))
    if not db_candidates:
        return []

    db_path = str(db_candidates[0])
    try:
        con = duckdb.connect(database=db_path, read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return tables
    except Exception:
        return []


def _check_package_availability(work_dir: Path) -> list[str]:
    """Check if any SQL files reference macros from packages not in dbt_packages/."""
    warnings = []
    dbt_pkg_dir = work_dir / "dbt_packages"
    installed_namespaces: set[str] = set()
    if dbt_pkg_dir.exists():
        for child in dbt_pkg_dir.iterdir():
            if child.is_dir():
                installed_namespaces.add(child.name)

    # Check SQL files for namespace.macro() references
    referenced_namespaces: set[str] = set()
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in (".claude", "dbt_packages", "target")):
            continue
        content = sql_file.read_text()
        # Match {{ namespace.macro_name(...) }} but not dbt_utils which is common
        for m in re.finditer(r'\{\{\s*(\w+)\.\w+\s*\(', content):
            ns = m.group(1)
            if ns not in ("ref", "source", "config", "this", "adapter", "var", "env_var"):
                referenced_namespaces.add(ns)

    missing = referenced_namespaces - installed_namespaces
    for ns in missing:
        if ns != "dbt_utils" or "dbt_utils" not in installed_namespaces:
            warnings.append(f"Package '{ns}' referenced in SQL but not found in dbt_packages/")
    return warnings


def build_agent_prompt(
    instance_id: str,
    instruction: str,
    work_dir: Path,
    eval_critical_models: set[str],
    max_turns: int = 20,
) -> str:
    """Build a focused, action-oriented prompt for the Claude CLI agent."""
    yml_models = _scan_yml_models(work_dir)
    complete_models, stub_models = _classify_sql_models(work_dir)

    # Detect pre-computed tables already in the DuckDB
    db_tables = set(_detect_precomputed_tables(work_dir))

    sql_models = complete_models | stub_models
    missing_models = yml_models - sql_models
    existing_models = yml_models & complete_models

    # Models that are "missing" SQL but already exist as DB tables
    # (e.g., pre-computed simulation tables) — don't treat as stubs
    precomputed_models = (missing_models | stub_models) & db_tables & eval_critical_models

    # Split missing models into priority (eval-critical) vs others
    missing_priority = missing_models & eval_critical_models
    missing_other = missing_models - eval_critical_models

    priority_str = ", ".join(sorted(missing_priority)) if missing_priority else "none"
    other_missing_str = ", ".join(sorted(missing_other)) if missing_other else "none"
    existing_str = ", ".join(sorted(existing_models)) if existing_models else "none"
    stubs_str = ", ".join(sorted(stub_models)) if stub_models else "none"

    # Extract dependency info for missing models
    model_deps = _extract_model_deps(work_dir)
    deps_lines = []
    for model_name in sorted(missing_models | stub_models):
        if model_name in model_deps:
            deps_lines.append(f"  {model_name} depends on: {', '.join(model_deps[model_name])}")
    deps_str = "\n".join(deps_lines) if deps_lines else "  (check YML refs: fields and existing SQL for dependency info)"

    # Extract column names from YML for priority models
    model_columns = _extract_model_columns(work_dir)
    col_spec_lines = []
    for model_name in sorted(missing_priority | (stub_models & eval_critical_models)):
        if model_name in model_columns:
            col_spec_lines.append(f"  {model_name}: {', '.join(model_columns[model_name])}")
    col_spec_str = "\n".join(col_spec_lines) if col_spec_lines else "  (read YML files for column specs)"

    # Build the selective dbt run command for priority models
    if missing_priority:
        priority_run_cmd = "dbt run --select " + " ".join(sorted(missing_priority))
    else:
        priority_run_cmd = "dbt run"

    # Detect whether this project uses dbt packages
    has_packages_yml = (work_dir / "packages.yml").exists()
    packages_hint = ""
    if has_packages_yml:
        # Find available staging models from packages
        pkg_stg_models = set()
        dbt_pkg_dir = work_dir / "dbt_packages"
        if dbt_pkg_dir.exists():
            for sql_file in dbt_pkg_dir.rglob("*.sql"):
                if sql_file.stem.startswith("stg_") or sql_file.stem.startswith("int_"):
                    pkg_stg_models.add(sql_file.stem)
        pkg_models_str = ", ".join(sorted(pkg_stg_models)[:20]) if pkg_stg_models else "check dbt_packages/"
        packages_hint = (
            f"\n- This project uses dbt packages with staging/intermediate models you can ref(): {pkg_models_str}"
            "\n- Run `dbt deps` first, then use ref('stg_model_name') for these package models"
        )

        # Add dbt.* macro hint only if existing SQL already references dbt. namespace
        existing_sql_uses_dbt_ns = False
        for sql_file in work_dir.rglob("*.sql"):
            if any(skip in str(sql_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                if "dbt." in sql_file.read_text():
                    existing_sql_uses_dbt_ns = True
                    break
            except Exception:
                pass

        if existing_sql_uses_dbt_ns:
            packages_hint += (
                "\n- dbt.* cross-adapter macros ARE available (from dbt-core): dbt.date_trunc(), dbt.length(), dbt.replace(), etc."
                "\n- These are different from package macros — use them freely in SQL: {{ dbt.date_trunc('month', 'date_col') }}"
            )

    prompt = f"""You are a dbt/DuckDB expert. Complete this dbt project in {work_dir}.
You have a budget of {max_turns} turns (tool calls). Plan accordingly — do not exhaust turns on exploration.

TASK: {instruction}

DATABASE: SignalPilot connection '{instance_id}' (DuckDB). Use mcp__signalpilot__* tools.

MISSING SQL MODELS — PRIORITY (evaluated, must complete): {priority_str}
MISSING SQL MODELS — OTHER (write if time permits): {other_missing_str}
INCOMPLETE SQL (stubs — must rewrite): {stubs_str}
EXISTING SQL MODELS: {existing_str}

MODEL DEPENDENCIES (build order — write dependencies first):
{deps_str}

REQUIRED COLUMNS FOR PRIORITY MODELS:
The evaluator checks that each expected column exists in your output (matched by VALUES, not position).
Every column below must appear in your SELECT with correct values. Missing or wrong-valued columns = failure.
{col_spec_str}

DO THIS IN ORDER:
1. {'Run: dbt deps' if has_packages_yml else 'SKIP dbt deps — no packages.yml, packages are pre-installed. NEVER run dbt deps on this project.'}
2. Run mcp__signalpilot__list_tables with connection_name="{instance_id}" (shows row counts, PKs, FKs)
3. Run mcp__signalpilot__explore_table on 2-3 key source tables (shows sample values — critical for writing correct SQL)
4. Read the YAML files that define the missing models to understand column requirements
5. Read existing SQL files carefully — copy their join patterns, column naming, and macro usage exactly
6. Write each missing .sql file (DuckDB SQL, use ref() and source() macros) — start with PRIORITY models
7. Run: {priority_run_cmd}
   Then run: dbt run (to build all models)
8. If errors, fix and re-run.
9. After success, verify: run mcp__signalpilot__query_database to check row counts and sample values of your output tables match expectations.
10. COLUMN CHECK — after every successful dbt run on a priority model:
    Run: SELECT * FROM <model_name> LIMIT 3
    Verify: all expected columns are present with reasonable values (not all NULL/0).

RULES:
- DuckDB SQL only (not PostgreSQL/MySQL)
- NEVER modify .yml or .yaml files — only create/edit .sql files
- CORRECT VALUES MATTER: The evaluator searches for matching columns by value, not position.
  Focus on getting correct computation logic (joins, aggregations, filters) rather than column order.
- Use ref('model_name') for upstream models, source('schema', 'table') for raw tables
- Check existing SQL files for naming conventions before writing new ones
- YML model definitions may contain a `refs:` key listing upstream model dependencies — use these as the primary guide for writing SQL
- Read YML column specs carefully: every column listed must appear in your SELECT
- FOCUS: Complete all PRIORITY models first. Only work on OTHER models if PRIORITY models are done and working.
- ROW ORDER: The evaluator ignores row ordering. Do NOT waste time on ORDER BY in model SQL — it has no effect on scoring.
- SPEED: Don't over-explore. Read 1-2 source tables, read the YML, write the SQL. Iterate on errors.
- VERIFY: After dbt run succeeds, query result tables to check row counts match expected data size. If a report table has far fewer rows than the source table, your WHERE/JOIN may be too restrictive.
- Use COUNT(*) not COUNT(DISTINCT col) unless the column spec explicitly says "distinct" or "unique"
- For aggregation columns named "total_X", use COUNT(*) or SUM(col) as appropriate — check what the gold data looks like by querying source tables first
- If a column needs to be computed (SUM, COUNT, CASE WHEN), check the source table schema first with explore_table
- For wide aggregation models with many category columns (counts per status, position, type):
  1. FIRST query the source table to see all distinct values: SELECT DISTINCT col FROM table ORDER BY col
  2. Map each distinct value to the exact column name from the YAML spec
  3. THEN write CASE WHEN statements — one per distinct value
  4. Use SUM(CASE WHEN status = 'Retired' THEN 1 ELSE 0 END) AS retired
  5. Any value not matching a named column goes into the catch-all column (e.g., p21plus, not_classified)
- If dbt run errors with 'No such file or directory' for a macro, the package may not be installed — write the logic inline instead
- String columns: always use COALESCE(col, '') to avoid NULL comparison issues
- DATE FORMAT: When a source column contains dates, ALWAYS check sample values with explore_table first. European dates (DD/MM/YYYY) must use STRPTIME(col, '%d/%m/%Y'). Never assume MM/DD/YYYY — check the data first. If day > 12 in any row, it's DD/MM format.
- COLUMN COUNT CHECK: Before finalizing any model, verify your SELECT produces all columns listed in the YAML. Missing columns = failure. Extra columns are OK (evaluator ignores them).
- {'NEVER run dbt deps — it will wipe the pre-installed packages!' if not has_packages_yml else 'Run dbt deps once at start to install packages'}{packages_hint}
- JOIN TYPE: Use INNER JOIN only when non-matching rows must be excluded. LEFT JOIN is required when left table is the spine (all customers, all products, all orders). A LEFT JOIN + WHERE right.col IS NOT NULL silently becomes INNER JOIN — avoid this pattern.
- FAN-OUT CHECK: After any JOIN, compare COUNT(*) of model to COUNT(DISTINCT pk) of source. If count(model) > count(DISTINCT pk), there is fan-out — fix before finishing the model.
- COLUMN NAMING: Always check the schema.yml for exact column names. Do NOT invent prefixes (e.g. 'attribution_') unless the YML explicitly defines them. Match names character-for-character.
- COMPLETENESS: Before finishing, verify ALL models in schema.yml have .sql files. Missing model = automatic zero score. Run: ls models/*.sql and compare to YML model list.
- DATE SPINES: When generating date series, query MIN/MAX dates from source data. Use UNNEST(GENERATE_SERIES(min_date::DATE, max_date::DATE, INTERVAL '1 day')). Never hardcode date ranges."""

    prompt += """

ROW COUNT VERIFICATION — Do this for every priority model after dbt run succeeds:

Step A: Baseline cardinality from primary source table:
  SELECT COUNT(*) AS source_rows, COUNT(DISTINCT <pk>) AS unique_pks FROM <source>

Step B: Count your output:
  SELECT COUNT(*) AS output_rows FROM <model>

Step C: Decide if count is correct:
  - Aggregation model (one row per group): output_rows == COUNT(DISTINCT group_key)
  - Pass-through/filter model: output_rows <= source_rows; verify against task description

Step D: If output_rows > expected → FAN-OUT:
  SELECT <join_key>, COUNT(*) FROM <model> GROUP BY 1 HAVING COUNT(*) > 1
  Fix: pre-aggregate the right-join table, or add DISTINCT, or use ROW_NUMBER() dedup.

Step E: If output_rows < expected → OVER-FILTER:
  Remove one WHERE/JOIN condition at a time, counting rows each time.
  Check if INNER JOIN should be LEFT JOIN (rows with no match are being silently dropped).

NEVER finish a priority model without running this 5-step audit."""

    # Add source table hints
    import yaml
    source_hints: list[str] = []
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "sources" in data:
                    for src in data["sources"]:
                        src_name = src.get("name", "")
                        tables = src.get("tables", [])
                        table_names = [t.get("name", "") for t in tables if isinstance(t, dict)]
                        if src_name and table_names:
                            source_hints.append(f"  source('{src_name}', '<table>') — tables: {', '.join(table_names)}")
            except Exception:
                pass

    source_str = "\n".join(source_hints) if source_hints else ""
    if source_str:
        prompt += f"\n\nAVAILABLE SOURCES:\n{source_str}"

    macros_dict = _scan_macros(work_dir)
    if macros_dict:
        macro_lines = [f"  {name}() — read macros/ directory to see full definition" for name in sorted(macros_dict)]
        prompt += "\n\nAVAILABLE MACROS (call with {{ macro_name() }} in Jinja):\n" + "\n".join(macro_lines)
        prompt += "\n- When writing new models, prefer using existing macros over re-implementing the logic inline."

    precomputed = _detect_precomputed_tables(work_dir)
    if precomputed:
        prompt += f"\n\nPRE-COMPUTED TABLES ALREADY IN DATABASE: {', '.join(precomputed)}"
        prompt += "\n- These tables already have data from pre-run simulations. Your summary models should SELECT from these tables, not re-run the simulation logic."

    checkpoint_turn = min(10, max_turns // 2)
    exploration_end = 3
    priority_deadline = max(4, max_turns - 8)

    prompt += f"""

TURN BUDGET PLAN — follow this allocation strictly:
- Turns 1-{exploration_end}: Discovery only (list_tables, explore 2-3 source tables, read YML)
- Turns {exploration_end + 1}-{priority_deadline}: Write and run ALL priority models
- Turns {priority_deadline + 1}+: Write other models, fix errors, verify

PRIORITY MODEL HARD CHECKPOINT:
By turn {checkpoint_turn}, every priority model must have a .sql file on disk.
If you reach turn {checkpoint_turn} and any priority model is still missing:
  - STOP all exploration and non-priority work immediately.
  - Write a minimal but syntactically correct SQL for each missing priority model right now.
  - A wrong-but-present model is evaluated and can be fixed; a missing model scores zero.
  - Do NOT write more than 2 tool calls on any non-priority model until ALL priority models exist."""

    prompt += """

SAMPLE VALUE CHECK — MANDATORY before finishing any priority model:
After the 5-step row count audit passes, run one additional query:
  SELECT * FROM <model_name> LIMIT 5

Look for these silent failure patterns in the output:
- A numeric column that is 0 or NULL for every row: aggregation or JOIN condition is wrong.
- A date column showing 1970 or far-future dates: date format mismatch (use STRPTIME).
- A string column that echoes the join key instead of a label: wrong column in SELECT.
- Any column that is identical for all 5 rows when it should vary: CASE WHEN literal typo.

Fix any of the above before finishing. This costs 1 tool call and catches the most common
silent-wrong-answer failures that pass row count checks but fail value evaluation."""

    prompt += """

DBT COMPILE FAILURE PROTOCOL — follow this order when dbt run fails:
1. Find the failing model name in the error output (look for lines with ERROR or "in model").
2. Run `dbt run --select <failing_model>` to isolate — do not re-run all models each attempt.
3. Compilation error (ref not found, jinja error):
   - Confirm the .sql filename exactly matches the ref() call: ref('stg_orders') needs stg_orders.sql
   - If a ref() target is a raw DuckDB table, create an ephemeral stub (ephemeral rule above)
4. Database error (column not found, type mismatch):
   - Run explore_table on the source to confirm exact column names and types
   - DuckDB type coercion is strict — add CAST() for any mixed-type expression
5. After fixing, run `dbt run --select <model>+` to rebuild the model and all its dependents.
6. Never run `dbt deps` unless this project has a packages.yml — it breaks pre-installed packages."""

    return prompt


# ── Agent runner ───────────────────────────────────────────────────────────────


def _run_claude_with_retry(
    cmd: list[str],
    cwd: str,
    timeout: int = 900,
    max_retries: int = 3,
    label: str = "agent",
) -> subprocess.CompletedProcess:
    """Run claude CLI with retry on 529/overloaded errors."""
    for attempt in range(1, max_retries + 1):
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 and ("529" in output or "Overloaded" in output or "overloaded" in output):
            if attempt < max_retries:
                wait = 30 * attempt
                log(f"API overloaded ({label}) — retry {attempt}/{max_retries} in {wait}s...")
                time.sleep(wait)
                continue
            else:
                log(f"API overloaded after {max_retries} retries ({label}) — giving up", "ERROR")
        return result
    return result  # type: ignore[possibly-undefined]


def run_agent(
    instance_id: str,
    instruction: str,
    work_dir: Path,
    model: str,
    max_turns: int,
    eval_critical_models: set[str],
) -> bool:
    """Run the Claude CLI agent in the work directory."""
    log_separator(f"AGENT  model={model}  max_turns={max_turns}  instance={instance_id}")

    prompt = build_agent_prompt(instance_id, instruction, work_dir, eval_critical_models, max_turns=max_turns)
    log(f"Prompt length: {len(prompt)} chars")

    claude_cmd = [
        "claude",
        "--model", model,
        "--permission-mode", "bypassPermissions",
        "--max-turns", str(max_turns),
        "--mcp-config", str(MCP_CONFIG),
        "-p", prompt,
    ]

    log(f"Running: claude --model {model} --max-turns {max_turns} --mcp-config ... -p <prompt>")
    log(f"Work dir: {work_dir}")

    start = time.monotonic()
    result = _run_claude_with_retry(claude_cmd, str(work_dir), timeout=900, label="main-agent")
    elapsed = time.monotonic() - start

    # Stream output to console
    if result.stdout:
        for line in result.stdout.splitlines():
            log(f"  [claude] {line}")
    if result.stderr:
        for line in result.stderr.splitlines():
            log(f"  [claude:err] {line}", "WARN")

    log(f"Claude CLI exit code: {result.returncode} ({elapsed:.1f}s)")
    return result.returncode == 0


# ── Evaluation ─────────────────────────────────────────────────────────────────

def _get_table_row_count(db_path: str, table_name: str) -> int | None:
    """Return SELECT COUNT(*) for table_name in a DuckDB database, or None on error."""
    import duckdb

    try:
        con = duckdb.connect(database=db_path, read_only=True)
        try:
            result = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
            if result is not None:
                return int(result[0])
            return None
        finally:
            con.close()
    except Exception:
        return None


def _sample_table_values(db_path: str, table_name: str, n: int = 5) -> list[dict] | None:
    """Return up to n rows from table as list of dicts, or None on error."""
    import duckdb

    try:
        con = duckdb.connect(database=db_path, read_only=True)
        try:
            rows = con.execute(f"SELECT * FROM {table_name} LIMIT {n}").fetchdf()
            return rows.to_dict(orient="records")
        finally:
            con.close()
    except Exception:
        return None


def evaluate(project_dir: Path, instance_id: str) -> tuple[bool, str]:
    """Evaluate the result against gold standard by comparing DuckDB table contents."""
    import duckdb
    import pandas as pd

    eval_config = load_eval_config(instance_id)
    if not eval_config:
        return False, "No evaluation config found in spider2_eval.jsonl"

    params = eval_config["evaluation"]["parameters"]
    # The DB filename in eval config may not match the actual filename — find it
    gold_db_candidates = list((GOLD_DIR / instance_id).glob("*.duckdb"))
    gold_db_path = str(gold_db_candidates[0]) if gold_db_candidates else str(GOLD_DIR / instance_id / params["gold"])
    result_db_candidates = list(project_dir.glob("*.duckdb"))
    result_db_path = str(result_db_candidates[0]) if result_db_candidates else str(project_dir / params["gold"])

    condition_tabs: list[str] | None = params.get("condition_tabs")
    condition_cols: list[list[int]] | None = params.get("condition_cols")
    ignore_orders: list[bool] | None = params.get("ignore_orders")

    log(f"Gold DB:   {gold_db_path}")
    log(f"Result DB: {result_db_path}")

    if not Path(result_db_path).exists():
        return False, f"Result DB not found: {result_db_path}"
    if not Path(gold_db_path).exists():
        return False, f"Gold DB not found: {gold_db_path}"

    def get_tables(db_path: str) -> list[str]:
        con = duckdb.connect(database=db_path, read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return tables

    def get_table_df(db_path: str, table_name: str):
        con = duckdb.connect(database=db_path, read_only=True)
        df = con.execute(f"SELECT * FROM {table_name}").fetchdf()
        con.close()
        return df

    result_tables = get_tables(result_db_path)
    gold_tables = get_tables(gold_db_path)
    log(f"Gold tables:   {gold_tables}")
    log(f"Result tables: {result_tables}")

    effective_tabs = condition_tabs if condition_tabs is not None else gold_tables
    effective_orders = ignore_orders if ignore_orders is not None else [False] * len(effective_tabs)
    effective_cols = condition_cols if condition_cols is not None else [[]] * len(effective_tabs)

    all_match = True
    details: list[str] = []

    for i, tab in enumerate(effective_tabs):
        log(f"Checking table: {tab}")

        if tab not in result_tables:
            msg = f"  {tab}: FAIL — table not in result DB (have: {result_tables})"
            details.append(msg)
            log(msg)
            all_match = False
            continue

        try:
            gold_df = get_table_df(gold_db_path, tab)
            pred_df = get_table_df(result_db_path, tab)
        except Exception as e:
            msg = f"  {tab}: ERROR reading table — {e}"
            details.append(msg)
            log(msg, "ERROR")
            all_match = False
            continue

        log(f"  Gold shape: {gold_df.shape}, Result shape: {pred_df.shape}")

        cols = effective_cols[i] if effective_cols[i] else []

        try:
            gold_sub = gold_df.iloc[:, cols] if cols else gold_df
        except IndexError as e:
            msg = f"  {tab}: FAIL — gold column index error: {e}"
            details.append(msg)
            log(msg)
            all_match = False
            continue

        if len(gold_sub) != len(pred_df):
            msg = f"  {tab}: FAIL — row count mismatch gold={len(gold_sub)} pred={len(pred_df)}"
            details.append(msg)
            log(msg)
            all_match = False
            continue

        def _official_compare(pred_df, gold_df, cols, ignore_order):
            """
            Replicates compare_pandas_table() from the official Spider2-DBT eval_utils.py.
            For each gold column (selected by positional index via cols), checks if ANY
            column in pred_df has a matching value vector. Row count must match.
            Returns (match: bool, failed_gold_col_name: str | None).
            """
            tolerance = 1e-2

            def vectors_match(v1, v2):
                try:
                    if ignore_order:
                        v1 = sorted(v1, key=lambda x: (x is None, str(x), isinstance(x, (int, float))))
                        v2 = sorted(v2, key=lambda x: (x is None, str(x), isinstance(x, (int, float))))
                    if len(v1) != len(v2):
                        return False
                    for a, b in zip(v1, v2):
                        if pd.isna(a) and pd.isna(b):
                            continue
                        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
                            if not math.isclose(float(a), float(b), abs_tol=tolerance):
                                return False
                        elif a != b:
                            return False
                    return True
                except Exception:
                    return False

            # Select gold columns by positional index (empty cols = all gold columns)
            if cols:
                try:
                    gold_sub = gold_df.iloc[:, cols]
                except IndexError as e:
                    return False, f"gold column index error: {e}"
            else:
                gold_sub = gold_df

            t_gold_list = gold_sub.transpose().values.tolist()
            t_pred_list = pred_df.transpose().values.tolist()

            for idx, gold_vec in enumerate(t_gold_list):
                if not any(vectors_match(gold_vec, pred_vec) for pred_vec in t_pred_list):
                    col_name = gold_sub.columns[idx] if idx < len(gold_sub.columns) else str(idx)
                    return False, col_name
            return True, None

        try:
            match, failed_col = _official_compare(pred_df, gold_df, cols, ignore_order=effective_orders[i])
            if match:
                msg = f"  {tab}: PASS"
                details.append(msg)
                log(msg)
            else:
                msg = f"  {tab}: FAIL — no pred column matched gold column '{failed_col}'"
                details.append(msg)
                log(msg)
                if isinstance(failed_col, str) and failed_col in gold_df.columns:
                    log(f"  Gold column '{failed_col}' values: {list(gold_df[failed_col].head(5))}")
                    log(f"  Pred columns: {list(pred_df.columns)}")
                    log(f"  Pred head:\n{pred_df.head(3)}")
                all_match = False
        except Exception as e:
            msg = f"  {tab}: FAIL — comparison error: {e}"
            details.append(msg)
            log(msg, "ERROR")
            all_match = False

    return all_match, "\n".join(details)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a Spider2-DBT task directly (no Docker) using Claude CLI + MCP"
    )
    parser.add_argument("instance_id", help="Task instance ID, e.g. chinook001")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Claude model to use")
    parser.add_argument("--max-turns", type=int, default=20, help="Max agent turns")
    parser.add_argument(
        "--skip-agent",
        action="store_true",
        help="Skip agent run, only evaluate existing results",
    )
    args = parser.parse_args()

    instance_id: str = args.instance_id
    model: str = args.model
    max_turns: int = args.max_turns

    log_separator(f"Spider2-DBT Direct Benchmark: {instance_id}")
    log(f"Model:     {model}")
    log(f"Max turns: {max_turns}")
    log(f"MCP config: {MCP_CONFIG}")
    log(f"Work dir:  {WORK_DIR / instance_id}")

    # ── Load task ──────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    task = load_task(instance_id)
    instruction: str = task["instruction"]
    log(f"Task loaded in {time.monotonic()-t0:.2f}s")
    log(f"Instruction: {instruction}")

    work_dir = WORK_DIR / instance_id

    # ── Load eval config to identify critical models ───────────────────────────
    eval_config = load_eval_config(instance_id)
    eval_critical_models: set[str] = set()
    if eval_config is not None:
        params = eval_config.get("evaluation", {}).get("parameters", {})
        condition_tabs = params.get("condition_tabs") or []
        eval_critical_models = set(condition_tabs)
        log(f"Eval-critical models: {sorted(eval_critical_models)}")

        # Check if gold DB exists (filename may differ from eval config)
        gold_db_list = list((GOLD_DIR / instance_id).glob("*.duckdb")) if (GOLD_DIR / instance_id).exists() else []
        gold_db = gold_db_list[0] if gold_db_list else GOLD_DIR / instance_id / params.get("gold", "")
        if not gold_db.exists():
            log(f"Gold DB not found: {gold_db} — this task cannot be evaluated!", "WARN")
    else:
        log(f"No eval config found for '{instance_id}' — treating all models as equal", "WARN")

    if not args.skip_agent:
        # ── Prepare workdir ────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 1: Prepare workdir")
        work_dir = prepare_workdir(instance_id)
        log(f"Workdir ready in {time.monotonic()-t0:.2f}s")

        # ── Write CLAUDE.md ────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 2: Write CLAUDE.md")
        write_claude_md(work_dir, instance_id, instruction)
        log(f"CLAUDE.md written in {time.monotonic()-t0:.2f}s")

        # ── Register connection ────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 3: Register DuckDB connection")
        duckdb_files = list(work_dir.glob("*.duckdb"))
        if duckdb_files:
            db_path = str(duckdb_files[0])
            register_local_connection(instance_id, db_path)
        else:
            log(f"No .duckdb files in {work_dir}", "WARN")
        log(f"Connection registered in {time.monotonic()-t0:.2f}s")

        # ── Scale max_turns based on number of missing + stub models ──────────
        yml_models = _scan_yml_models(work_dir)
        complete_sql_models, stub_sql_models = _classify_sql_models(work_dir)
        missing_models_set = yml_models - (complete_sql_models | stub_sql_models)
        work_count = len(missing_models_set) + len(stub_sql_models)

        if args.max_turns == 20:
            # Auto-scale based on work complexity
            # Count total SQL files for project complexity
            total_sql = len(list(work_dir.rglob("*.sql")))
            has_macros = any(True for _ in (work_dir / "macros").rglob("*.sql")) if (work_dir / "macros").exists() else False

            if work_count >= 7 or total_sql > 100:
                max_turns = 40
            elif work_count >= 4 or (work_count >= 2 and has_macros):
                max_turns = 30
            else:
                max_turns = 20
            log(f"Auto-scaled max_turns={max_turns} for {work_count} model(s) needing work ({len(missing_models_set)} missing, {len(stub_sql_models)} stubs, {total_sql} total SQL files)")

        # ── Check package availability ────────────────────────────────────────
        pkg_warnings = _check_package_availability(work_dir)
        for w in pkg_warnings:
            log(w, "WARN")

        # -- Pre-populate SQL templates for missing priority models
        created_templates = _create_sql_templates(work_dir, eval_critical_models)
        if created_templates:
            log(f"Pre-populated {len(created_templates)} SQL template(s) for priority models")

        # -- Auto-create ephemeral stubs for ref() targets that are raw DuckDB tables
        created_stubs = _create_ephemeral_stubs(work_dir)
        if created_stubs:
            log(f"Auto-created {len(created_stubs)} ephemeral stub(s): {', '.join(sorted(created_stubs))}")

        # ── Run agent ──────────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 4: Run Claude agent")
        agent_ok = run_agent(
            instance_id=instance_id,
            instruction=instruction,
            work_dir=work_dir,
            model=model,
            max_turns=max_turns,
            eval_critical_models=eval_critical_models,
        )
        elapsed = time.monotonic() - t0
        log(f"Agent finished in {elapsed:.1f}s — {'success' if agent_ok else 'failed/partial'}")

    # ── Post-agent dbt run ──────────────────────────────────────────────────
    if not args.skip_agent:
        t0 = time.monotonic()
        log_separator("Step 4b: Final dbt deps + dbt run (post-agent safety net)")
        # Only run dbt deps if packages.yml exists — otherwise it wipes pre-installed packages!
        if (work_dir / "packages.yml").exists():
            subprocess.run(
                ["/home/agentuser/.local/bin/dbt", "deps"],
                cwd=str(work_dir),
                capture_output=True, text=True, timeout=120,
            )

        # First try selective run on eval-critical models and their upstream deps
        if eval_critical_models:
            select_args = (
                ["/home/agentuser/.local/bin/dbt", "run", "--select"]
                + [f"+{m}" for m in sorted(eval_critical_models)]
            )
            dbt_result = subprocess.run(
                select_args,
                cwd=str(work_dir),
                capture_output=True, text=True, timeout=120,
            )
            if dbt_result.returncode == 0:
                log(f"Selective dbt run (eval-critical) PASSED in {time.monotonic()-t0:.1f}s")
            else:
                log(f"Selective dbt run (eval-critical) FAILED in {time.monotonic()-t0:.1f}s")
                for line in (dbt_result.stdout + dbt_result.stderr).strip().splitlines()[-20:]:
                    log(f"  dbt: {line}")
        else:
            dbt_result = subprocess.run(
                ["/home/agentuser/.local/bin/dbt", "run"],
                cwd=str(work_dir),
                capture_output=True, text=True, timeout=120,
            )
            if dbt_result.returncode == 0:
                log(f"Final dbt run PASSED in {time.monotonic()-t0:.1f}s")
            else:
                log(f"Final dbt run FAILED in {time.monotonic()-t0:.1f}s")
                for line in (dbt_result.stdout + dbt_result.stderr).strip().splitlines()[-20:]:
                    log(f"  dbt: {line}")

        # If selective run failed, try a quick fix agent
        if eval_critical_models and dbt_result.returncode != 0:
            error_output = (dbt_result.stdout + dbt_result.stderr).strip()[-2000:]
            fix_prompt = f"""Fix dbt errors in {work_dir}. The task: {instruction}

dbt run failed with this error:
{error_output}

Steps:
1. Read the error carefully — identify which model failed and why
2. Read the failing SQL file and fix the error
3. Run: dbt run --select {' '.join(sorted(eval_critical_models))}
4. If it passes, done. If not, fix and retry.

RULES: DuckDB SQL only. Do NOT modify .yml files. Use STRPTIME for non-ISO date parsing.{"" if (work_dir / "packages.yml").exists() else " NEVER run dbt deps — it will wipe pre-installed packages!"}"""

            # Add column specs for eval-critical models to fix prompt
            col_specs: list[str] = []
            model_columns = _extract_model_columns(work_dir)
            for model_name in sorted(eval_critical_models):
                if model_name in model_columns:
                    col_specs.append(f"  {model_name} must have these columns in order: {', '.join(model_columns[model_name])}")
            col_spec_hint = "\n".join(col_specs) if col_specs else ""

            if col_spec_hint:
                fix_prompt += f"\n\nREQUIRED COLUMN SPECS (your SQL must produce these exact columns):\n{col_spec_hint}"

            fix_prompt += (
                "\n\nAfter fixing, verify your output:"
                "\n- Run mcp__signalpilot__query_database with: SELECT COUNT(*), COUNT(DISTINCT <pk>) FROM <model_table>"
                "\n- If count seems wrong, check your JOIN conditions for fan-out"
            )

            log("Running quick-fix agent (10 turns)...")
            fix_cmd = [
                "claude",
                "--model", model,
                "--permission-mode", "bypassPermissions",
                "--max-turns", "10",
                "--mcp-config", str(MCP_CONFIG),
                "-p", fix_prompt,
            ]
            fix_result = _run_claude_with_retry(fix_cmd, str(work_dir), timeout=300, label="quick-fix")
            if fix_result.returncode == 0:
                log("Fix agent completed")
            else:
                log("Fix agent failed")

        # Then try full run (best effort — don't fail on this)
        # Run eval-critical first, then full run for remaining models
        if eval_critical_models:
            subprocess.run(
                ["/home/agentuser/.local/bin/dbt", "run", "--select"]
                + [f"+{m}" for m in sorted(eval_critical_models)],
                cwd=str(work_dir),
                capture_output=True, text=True, timeout=300,
            )
        subprocess.run(
            ["/home/agentuser/.local/bin/dbt", "run", "--no-fail-fast"],
            cwd=str(work_dir),
            capture_output=True, text=True, timeout=300,
        )

        # Row-count fix pass — runs even when dbt succeeds
        if eval_critical_models:
            gold_db_candidates = list((GOLD_DIR / instance_id).glob("*.duckdb"))
            pred_db_candidates = list(work_dir.glob("*.duckdb"))
            mismatches: list[tuple[str, int, int]] = []
            if gold_db_candidates and pred_db_candidates:
                for tab in sorted(eval_critical_models):
                    gold_n = _get_table_row_count(str(gold_db_candidates[0]), tab)
                    pred_n = _get_table_row_count(str(pred_db_candidates[0]), tab)
                    if gold_n is not None and pred_n is not None:
                        delta = abs(pred_n - gold_n)
                        pct = delta / max(gold_n, 1) * 100
                        if pct > 2 or delta > 10:
                            mismatches.append((tab, gold_n, pred_n))
                if mismatches:
                    log(f"Row-count mismatches detected: {mismatches}")
                    rc_fix_parts: list[str] = []
                    for tab, gold_n, pred_n in mismatches:
                        too_many = pred_n > gold_n
                        direction = (
                            f"TOO MANY (+{pred_n - gold_n} rows) — likely JOIN fan-out"
                            if too_many
                            else f"TOO FEW (-{gold_n - pred_n} rows) — likely over-filter or wrong JOIN type"
                        )
                        fix_step_c = (
                            f"Find duplicates: SELECT <join_key>, COUNT(*) FROM {tab} GROUP BY 1 HAVING COUNT(*)>1"
                            if too_many
                            else "Find dropped rows: remove each WHERE/JOIN condition one at a time"
                        )
                        rc_fix_parts.append(
                            f"TABLE: {tab}\n"
                            f"GOLD row count: {gold_n}\n"
                            f"YOUR row count:  {pred_n}\n"
                            f"DIRECTION: {direction}\n"
                            f"\nSTEPS:\n"
                            f"1. Read the SQL file for {tab}\n"
                            f"2. Run the Row Count Audit:\n"
                            f"   a. SELECT COUNT(*), COUNT(DISTINCT <pk>) FROM each source table\n"
                            f"   b. SELECT COUNT(*) FROM {tab}\n"
                            f"   c. {fix_step_c}\n"
                            f"3. Fix the SQL: pre-aggregate joins, switch INNER to LEFT JOIN, or remove wrong filters\n"
                            f"4. Run: dbt run --select {tab}\n"
                            f"5. Verify: SELECT COUNT(*) FROM {tab} — should be close to {gold_n}"
                        )
                    rc_fix_prompt = (
                        f"Fix row count mismatches in {work_dir}.\n\n"
                        f"TASK: {instruction}\n\n"
                        + "\n\n---\n\n".join(rc_fix_parts)
                        + "\n\nDuckDB only. Do NOT modify .yml files."
                    )
                    model_columns = _extract_model_columns(work_dir)
                    rc_col_specs: list[str] = []
                    for tab, _, _ in mismatches:
                        if tab in model_columns:
                            rc_col_specs.append(f"  {tab}: {', '.join(model_columns[tab])}")
                    if rc_col_specs:
                        rc_fix_prompt += "\n\nREQUIRED COLUMN SPECS:\n" + "\n".join(rc_col_specs)
                    log("Running row-count fix agent (12 turns)...")
                    rc_fix_cmd = [
                        "claude",
                        "--model", model,
                        "--permission-mode", "bypassPermissions",
                        "--max-turns", "12",
                        "--mcp-config", str(MCP_CONFIG),
                        "-p", rc_fix_prompt,
                    ]
                    rc_fix_result = _run_claude_with_retry(rc_fix_cmd, str(work_dir), timeout=360, label="row-count-fix")
                    if rc_fix_result.returncode == 0:
                        log("Row-count fix agent completed")
                    else:
                        log("Row-count fix agent failed")
                    # Re-run dbt to apply fixes
                    subprocess.run(
                        ["/home/agentuser/.local/bin/dbt", "run", "--select"]
                        + [f"+{m}" for m in sorted(eval_critical_models)],
                        cwd=str(work_dir),
                        capture_output=True, text=True, timeout=300,
                    )

            # Value-check fix phase — runs for tables with matching row counts but wrong values
            if gold_db_candidates and pred_db_candidates:
                mismatch_tabs = {tab for tab, _, _ in mismatches} if mismatches else set()
                value_mismatches: list[tuple[str, list[tuple[str, object, object]]]] = []
                for tab in sorted(eval_critical_models):
                    if tab in mismatch_tabs:
                        continue
                    gold_rows = _sample_table_values(str(gold_db_candidates[0]), tab)
                    pred_rows = _sample_table_values(str(pred_db_candidates[0]), tab)
                    if gold_rows is None or pred_rows is None:
                        continue
                    if not gold_rows or not pred_rows:
                        continue
                    col_diffs: list[tuple[str, object, object]] = []
                    gold_cols_lower = {k.lower(): k for k in gold_rows[0].keys()}
                    pred_cols_lower = {k.lower(): k for k in pred_rows[0].keys()}
                    common_cols = set(gold_cols_lower) & set(pred_cols_lower)
                    for col_lower in sorted(common_cols):
                        gold_col = gold_cols_lower[col_lower]
                        pred_col = pred_cols_lower[col_lower]
                        gold_vals = [str(r.get(gold_col)) for r in gold_rows]
                        pred_vals = [str(r.get(pred_col)) for r in pred_rows]
                        if any(gv != pv for gv, pv in zip(gold_vals, pred_vals)):
                            col_diffs.append((col_lower, gold_vals, pred_vals))
                    if col_diffs:
                        value_mismatches.append((tab, col_diffs))
                if value_mismatches:
                    log(f"Value mismatches detected in {[t for t, _ in value_mismatches]}")
                    model_columns = _extract_model_columns(work_dir)
                    val_fix_parts: list[str] = []
                    for tab, col_diffs in value_mismatches:
                        mismatched_col_list = ", ".join(col for col, _, _ in col_diffs)
                        col_lines = "\n".join(
                            f"    {col}: gold={gv}  yours={pv}"
                            for col, gv, pv in col_diffs
                        )
                        col_spec_line = (
                            f"\n  REQUIRED COLUMNS (in order): {', '.join(model_columns[tab])}"
                            if tab in model_columns else ""
                        )
                        val_fix_parts.append(
                            f"TABLE: {tab}\n"
                            f"  MISMATCHED COLUMNS (gold vs your output):\n"
                            f"{col_lines}"
                            f"{col_spec_line}\n"
                            f"\nSTEPS:\n"
                            f"1. Read the SQL file for {tab}\n"
                            f"2. Query your output: SELECT {mismatched_col_list} FROM {tab} LIMIT 5\n"
                            f"3. Identify the formula/join/transformation error\n"
                            f"4. Fix the SQL and run: dbt run --select {tab}\n"
                            f"5. Verify values match the expected pattern"
                        )
                    val_fix_prompt = (
                        f"Fix value mismatches in {work_dir}.\n\n"
                        f"TASK: {instruction}\n\n"
                        "Row counts are correct but column values are wrong in these tables:\n\n"
                        + "\n\n---\n\n".join(val_fix_parts)
                        + "\n\nDuckDB only. Do NOT modify .yml files."
                    )
                    log("Running value-fix agent (10 turns)...")
                    val_fix_cmd = [
                        "claude",
                        "--model", model,
                        "--permission-mode", "bypassPermissions",
                        "--max-turns", "10",
                        "--mcp-config", str(MCP_CONFIG),
                        "-p", val_fix_prompt,
                    ]
                    val_fix_result = _run_claude_with_retry(val_fix_cmd, str(work_dir), timeout=240, label="value-fix")
                    if val_fix_result.returncode == 0:
                        log("Value-fix agent completed")
                    else:
                        log("Value-fix agent failed")

    # ── Evaluate ───────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    log_separator("Step 5: Evaluate against gold standard")

    if not work_dir.exists():
        log(f"Work dir not found: {work_dir}", "ERROR")
        log("Run without --skip-agent first to generate results.")
        sys.exit(1)

    try:
        passed, details = evaluate(work_dir, instance_id)
    except Exception as e:
        import traceback
        log(f"Evaluation error: {e}", "ERROR")
        traceback.print_exc()
        log_separator("RESULT: ERROR")
        sys.exit(1)

    log(f"Evaluation finished in {time.monotonic()-t0:.2f}s")
    print(details)
    log_separator(f"RESULT: {'PASS' if passed else 'FAIL'}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
