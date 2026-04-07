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
1. Run `dbt deps` once at the start.
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
) -> str:
    """Build a focused, action-oriented prompt for the Claude CLI agent."""
    yml_models = _scan_yml_models(work_dir)
    complete_models, stub_models = _classify_sql_models(work_dir)

    sql_models = complete_models | stub_models
    missing_models = yml_models - sql_models
    existing_models = yml_models & complete_models

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

    prompt = f"""You are a dbt/DuckDB expert. Complete this dbt project in {work_dir}.

TASK: {instruction}

DATABASE: SignalPilot connection '{instance_id}' (DuckDB). Use mcp__signalpilot__* tools.

MISSING SQL MODELS — PRIORITY (evaluated, must complete): {priority_str}
MISSING SQL MODELS — OTHER (write if time permits): {other_missing_str}
INCOMPLETE SQL (stubs — must rewrite): {stubs_str}
EXISTING SQL MODELS: {existing_str}

MODEL DEPENDENCIES (build order — write dependencies first):
{deps_str}

REQUIRED COLUMNS FOR PRIORITY MODELS (your SELECT must produce these columns IN THIS ORDER):
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

RULES:
- DuckDB SQL only (not PostgreSQL/MySQL)
- NEVER modify .yml or .yaml files — only create/edit .sql files
- Your SQL must produce ALL columns listed in the YML definition for each model, in the exact order specified in the YML
- Use ref('model_name') for upstream models, source('schema', 'table') for raw tables
- Check existing SQL files for naming conventions before writing new ones
- YML model definitions may contain a `refs:` key listing upstream model dependencies — use these as the primary guide for writing SQL
- Read YML column specs carefully: every column listed must appear in your SELECT
- FOCUS: Complete all PRIORITY models first. Only work on OTHER models if PRIORITY models are done and working.
- SPEED: Don't over-explore. Read 1-2 source tables, read the YML, write the SQL. Iterate on errors.
- When writing SQL, produce columns in the EXACT order they appear in the YAML model definition (top to bottom)
- If a column needs to be computed (SUM, COUNT, CASE WHEN), check the source table schema first with explore_table
- For wide aggregation models (e.g., counts by category), use CASE WHEN inside SUM/COUNT, not PIVOT
- If dbt run errors with 'No such file or directory' for a macro, the package may not be installed — write the logic inline instead
- String columns: always use COALESCE(col, '') to avoid NULL comparison issues
- {'NEVER run dbt deps — it will wipe the pre-installed packages!' if not has_packages_yml else 'Run dbt deps once at start to install packages'}{packages_hint}"""

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

    return prompt


# ── Agent runner ───────────────────────────────────────────────────────────────

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

    prompt = build_agent_prompt(instance_id, instruction, work_dir, eval_critical_models)
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
    result = subprocess.run(
        claude_cmd,
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=600,
    )
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

        cols = effective_cols[i] if effective_cols[i] else list(range(len(gold_df.columns)))

        try:
            gold_sub = gold_df.iloc[:, cols]
        except IndexError as e:
            msg = f"  {tab}: FAIL — gold column index error: {e}"
            details.append(msg)
            log(msg)
            all_match = False
            continue

        # Try positional match first; if indices are out of bounds for pred,
        # fall back to column-name matching (case-insensitive).
        try:
            pred_sub = pred_df.iloc[:, cols]
        except IndexError:
            # Column indices don't exist in pred — try matching by column name
            gold_col_names = [c.lower() for c in gold_sub.columns]
            pred_col_map = {c.lower(): c for c in pred_df.columns}
            matched_pred_cols = []
            for gc in gold_col_names:
                if gc in pred_col_map:
                    matched_pred_cols.append(pred_col_map[gc])
                else:
                    matched_pred_cols = []
                    break
            if matched_pred_cols:
                pred_sub = pred_df[matched_pred_cols]
                log(f"  Used column-name matching (positional indices out of bounds)")
            else:
                msg = f"  {tab}: FAIL — column index error: pred has {len(pred_df.columns)} cols, need indices {cols}"
                details.append(msg)
                log(msg)
                log(f"  Gold cols: {list(gold_sub.columns)}, Pred cols: {list(pred_df.columns)}")
                all_match = False
                continue

        if gold_sub.shape != pred_sub.shape:
            # Before failing, try column-name matching if shapes differ
            gold_col_names_lower = [c.lower() for c in gold_sub.columns]
            pred_col_map = {c.lower(): c for c in pred_df.columns}
            matched_pred_cols = []
            for gc in gold_col_names_lower:
                if gc in pred_col_map:
                    matched_pred_cols.append(pred_col_map[gc])
            if len(matched_pred_cols) == len(gold_sub.columns):
                pred_sub_by_name = pred_df[matched_pred_cols]
                if gold_sub.shape == pred_sub_by_name.shape:
                    pred_sub = pred_sub_by_name
                    log(f"  Used column-name matching (positional shapes differed)")

        if gold_sub.shape != pred_sub.shape:
            msg = (
                f"  {tab}: FAIL — shape mismatch "
                f"gold={gold_sub.shape} pred={pred_sub.shape}"
            )
            details.append(msg)
            log(msg)
            log(f"  Gold cols: {list(gold_sub.columns)}")
            log(f"  Pred cols: {list(pred_sub.columns)}")
            log(f"  Gold head:\n{gold_sub.head(3)}")
            log(f"  Pred head:\n{pred_sub.head(3)}")
            all_match = False
            continue

        # --- Comparison helper ---
        def _compare_dfs(g_df, p_df, sort_rows: bool) -> tuple[bool, str | None]:
            """Compare two DataFrames column-by-column. Returns (match, mismatch_col_name)."""
            g_cols = list(g_df.columns)
            ncols = list(range(len(g_cols)))
            gc = g_df.copy()
            pc = p_df.copy()
            gc.columns = ncols
            pc.columns = ncols
            if sort_rows:
                # Convert all columns to string for sorting to avoid mixed-type errors
                gc_sort_key = gc.astype(str)
                pc_sort_key = pc.astype(str)
                gc = gc.iloc[gc_sort_key.sort_values(by=ncols).index].reset_index(drop=True)
                pc = pc.iloc[pc_sort_key.sort_values(by=ncols).index].reset_index(drop=True)
            for ci in range(len(ncols)):
                g_s = gc.iloc[:, ci]
                p_s = pc.iloc[:, ci]
                is_num = pd.api.types.is_numeric_dtype(g_s) and pd.api.types.is_numeric_dtype(p_s)
                is_dt = pd.api.types.is_datetime64_any_dtype(g_s) or pd.api.types.is_datetime64_any_dtype(p_s)
                if is_num:
                    gn = pd.to_numeric(g_s, errors="coerce").fillna(0)
                    pn = pd.to_numeric(p_s, errors="coerce").fillna(0)
                    if not all(
                        abs(a - b) < 0.01 or (abs(b) > 1e-6 and abs(a - b) / abs(b) < 0.01)
                        for a, b in zip(gn, pn)
                    ):
                        return False, g_cols[ci] if ci < len(g_cols) else str(ci)
                elif is_dt:
                    # Compare as timestamps — handles format differences like .000 suffix
                    try:
                        gt = pd.to_datetime(g_s, errors="coerce", format="mixed")
                        pt = pd.to_datetime(p_s, errors="coerce", format="mixed")
                        # Both NaT = match, one NaT = mismatch
                        if not all(
                            (pd.isna(a) and pd.isna(b)) or (not pd.isna(a) and not pd.isna(b) and a == b)
                            for a, b in zip(gt, pt)
                        ):
                            return False, g_cols[ci] if ci < len(g_cols) else str(ci)
                    except Exception:
                        # Fall back to string comparison
                        gs = g_s.astype(str).fillna("")
                        ps = p_s.astype(str).fillna("")
                        if not all(a.strip().lower() == b.strip().lower() for a, b in zip(gs, ps)):
                            return False, g_cols[ci] if ci < len(g_cols) else str(ci)
                else:
                    gs = g_s.astype(str).fillna("")
                    ps = p_s.astype(str).fillna("")
                    if not all(a.strip().lower() == b.strip().lower() for a, b in zip(gs, ps)):
                        return False, g_cols[ci] if ci < len(g_cols) else str(ci)
            return True, None

        orig_gold_cols = list(gold_sub.columns)
        sort_rows = effective_orders[i]

        try:
            # Attempt 1: positional comparison
            match, mismatch_col = _compare_dfs(gold_sub, pred_sub, sort_rows)

            # Attempt 2: if positional failed, try column-name matching
            if not match:
                gold_col_lower = [c.lower() for c in gold_sub.columns]
                pred_col_map = {c.lower(): c for c in pred_df.columns}
                matched = [pred_col_map[gc] for gc in gold_col_lower if gc in pred_col_map]
                if len(matched) == len(gold_sub.columns):
                    pred_by_name = pred_df[matched]
                    if gold_sub.shape == pred_by_name.shape:
                        match2, mismatch2 = _compare_dfs(gold_sub, pred_by_name, sort_rows)
                        if match2:
                            match, mismatch_col = True, None
                            log(f"  Column-name matching rescued positional mismatch")

            if match:
                msg = f"  {tab}: PASS ({gold_sub.shape[0]} rows, {len(cols)} cols)"
                details.append(msg)
                log(msg)
            else:
                msg = f"  {tab}: FAIL — values don't match (column: {mismatch_col})"
                details.append(msg)
                log(msg)
                if mismatch_col is not None:
                    mismatch_idx = orig_gold_cols.index(mismatch_col) if mismatch_col in orig_gold_cols else 0
                    log(f"  Gold values: {list(gold_sub.iloc[:5, mismatch_idx])}")
                    log(f"  Pred values: {list(pred_sub.iloc[:5, mismatch_idx])}")
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

            log("Running quick-fix agent (10 turns)...")
            fix_cmd = [
                "claude",
                "--model", model,
                "--permission-mode", "bypassPermissions",
                "--max-turns", "10",
                "--mcp-config", str(MCP_CONFIG),
                "-p", fix_prompt,
            ]
            fix_result = subprocess.run(
                fix_cmd, cwd=str(work_dir),
                capture_output=True, text=True, timeout=300,
            )
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
