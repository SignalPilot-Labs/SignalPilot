"""Working-directory lifecycle helpers for the dbt benchmark runners."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .logging import log
from .paths import EXAMPLES_DIR, PROJECT_ROOT, SKILLS_SRC, SPIDER2_LITE_DIR, WORK_DIR

if TYPE_CHECKING:
    from .suite import DBBackend, SuiteConfig


def force_rmtree(path: Path) -> None:
    """Remove a directory tree, handling Windows read-only permission errors."""

    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)

    shutil.rmtree(path, onerror=on_error)


def prepare_workdir(instance_id: str, data_dir: Path | None = None) -> Path:
    """Copy the task's dbt project into a fresh working directory under _dbt_workdir/.

    When data_dir is provided, copies from data_dir/instance_id instead of
    EXAMPLES_DIR/instance_id.
    """
    src = (data_dir if data_dir is not None else EXAMPLES_DIR) / instance_id
    dst = WORK_DIR / instance_id
    if dst.exists():
        force_rmtree(dst)
    shutil.copytree(src, dst)
    log(f"Copied task files: {src} -> {dst}")

    # Copy .mcp.json so Claude Code discovers SignalPilot MCP tools
    mcp_json_src = PROJECT_ROOT / ".mcp.json"
    if mcp_json_src.exists():
        shutil.copy2(mcp_json_src, dst / ".mcp.json")
        log("Copied .mcp.json for MCP tool discovery")

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

    # Initialize a git repo so Claude Code discovers skills in .claude/skills/
    subprocess.run(["git", "init"], cwd=str(dst), capture_output=True)

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

## Verification & Analysis Tools (use after dbt build)
- `mcp__signalpilot__check_model_schema` — compare materialized columns vs YML expected columns
- `mcp__signalpilot__validate_model_output` — row count + fan-out detection post-build
- `mcp__signalpilot__analyze_grain` — check cardinality / unique keys
- `mcp__signalpilot__audit_model_sources` — single-call cardinality audit: row counts for all upstream sources + model output, fan-out/over-filter ratios, NULL fraction and constant-value scan on all output columns
- `mcp__signalpilot__compare_join_types` — compare row counts for INNER/LEFT/RIGHT/FULL OUTER JOIN between two tables to pick the right JOIN type
- `mcp__signalpilot__dbt_error_parser` — parse dbt error text into fix suggestions
- `mcp__signalpilot__generate_sql_skeleton` — generate SELECT template from YML column list

## Key Rules
- Always use `{{ config(materialized='table') }}` at the top of every model
- Column names in YML are exact — copy them into SELECT aliases character-for-character
- LEFT JOIN is the default; use INNER JOIN only when the task says "with" or "due to" (entities explicitly excluded)
"""
    (work_dir / "CLAUDE.md").write_text(content)
    log(f"Wrote CLAUDE.md to {work_dir}")


def prepare_sql_workdir(
    instance_id: str,
    config: "SuiteConfig",
    task: dict,
    sqlite_db_dir: Path | None = None,
) -> Path:
    """Create a fresh working directory for a SQL-suite task (no dbt project copy).

    - Creates config.work_dir / instance_id
    - Copies .mcp.json for MCP tool discovery
    - Copies only SQL-relevant skills (config.skills) into .claude/skills/
    - Runs git init for skill discovery
    - For lite-sqlite: copies the SQLite DB file into the workdir
    """
    from .suite import BenchmarkSuite

    dst = config.work_dir / instance_id
    if dst.exists():
        force_rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    log(f"Created SQL workdir: {dst}")

    # Copy .mcp.json for MCP tool discovery
    mcp_json_src = PROJECT_ROOT / ".mcp.json"
    if mcp_json_src.exists():
        shutil.copy2(mcp_json_src, dst / ".mcp.json")
        log("Copied .mcp.json for MCP tool discovery")
    else:
        log(f".mcp.json not found at {mcp_json_src}", "WARN")

    # Copy only the suite-specific skills into .claude/skills/
    skills_dst = dst / ".claude" / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    copied_skills: list[str] = []
    for skill_name in config.skills:
        skill_src = SKILLS_SRC / skill_name
        if skill_src.exists():
            shutil.copytree(
                skill_src,
                skills_dst / skill_name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("*.json", "__pycache__"),
            )
            copied_skills.append(skill_name)
        else:
            log(f"Skill not found, skipping: {skill_src}", "WARN")
    log(f"Copied {len(copied_skills)} skills into {skills_dst}: {copied_skills}")

    # Initialize git repo so Claude Code discovers skills in .claude/skills/
    subprocess.run(["git", "init"], cwd=str(dst), capture_output=True)

    # For spider2-lite SQLite tasks, copy the .sqlite DB file into the workdir
    if config.suite == BenchmarkSuite.LITE and task.get("type") == "sqlite":
        db_id: str = task.get("db_id", "")
        if db_id:
            if sqlite_db_dir is not None:
                sqlite_db_src = sqlite_db_dir / f"{db_id}.sqlite"
            else:
                sqlite_db_src = SPIDER2_LITE_DIR / "resource" / "databases" / "sqlite" / f"{db_id}.sqlite"
            if sqlite_db_src.exists():
                shutil.copy2(sqlite_db_src, dst / f"{db_id}.sqlite")
                log(f"Copied SQLite DB: {sqlite_db_src} -> {dst / f'{db_id}.sqlite'}")
            else:
                log(f"SQLite DB not found: {sqlite_db_src}", "WARN")
        else:
            log("sqlite task missing 'db_id' field — cannot copy DB file", "WARN")

    return dst


def write_sql_claude_md(
    work_dir: Path,
    instance_id: str,
    instruction: str,
    db_backend: "DBBackend",
    connection_name: str,
) -> None:
    """Write CLAUDE.md tailored for SQL (non-dbt) tasks."""
    from .suite import DBBackend

    backend_rules = {
        DBBackend.SNOWFLAKE: (
            "- Use Snowflake SQL syntax\n"
            "- QUALIFY for window function filtering\n"
            "- ILIKE for case-insensitive string matching\n"
            "- FLATTEN / LATERAL FLATTEN for arrays and semi-structured data\n"
            "- Date functions: DATEADD, DATEDIFF, DATE_TRUNC\n"
            "- VARIANT / OBJECT_CONSTRUCT for semi-structured columns"
        ),
        DBBackend.BIGQUERY: (
            "- Use BigQuery SQL (Standard SQL) syntax\n"
            "- UNNEST for array expansion\n"
            "- DATE_DIFF, DATE_ADD, DATE_TRUNC for date arithmetic\n"
            "- Table references: `project.dataset.table` (backtick-quoted)\n"
            "- EXCEPT and REPLACE in SELECT for column exclusion/override\n"
            "- ARRAY_AGG, STRUCT for complex types"
        ),
        DBBackend.SQLITE: (
            "- Use SQLite SQL syntax\n"
            "- Use substr() / instr() — no POSITION() or SPLIT_PART()\n"
            "- String concatenation: || operator\n"
            "- No ILIKE — use LIKE (case-insensitive by default for ASCII)\n"
            "- Limited window function support in older SQLite versions\n"
            "- No FULL OUTER JOIN — simulate with UNION of LEFT JOINs"
        ),
        DBBackend.DUCKDB: (
            "- Use DuckDB SQL syntax\n"
            "- QUALIFY for window function filtering\n"
            "- Date functions: DATE_TRUNC, DATE_DIFF, INTERVAL arithmetic\n"
            "- STRPTIME for non-ISO date parsing"
        ),
    }
    rules = backend_rules.get(db_backend, "- Use standard SQL syntax")

    content = f"""# Spider2 SQL Benchmark Task: {instance_id}

## Your Task
{instruction}

## Database Access
The database is registered in SignalPilot as connection `{connection_name}`.
Backend: **{db_backend.value}**

Use SignalPilot MCP tools to explore and query the database:
- `mcp__signalpilot__schema_overview` — quick overview of all schemas and tables
- `mcp__signalpilot__schema_ddl` — full schema as DDL (CREATE TABLE statements)
- `mcp__signalpilot__list_tables` — list all tables
- `mcp__signalpilot__describe_table` — column details for a specific table
- `mcp__signalpilot__explore_table` — sample values and statistics for a table
- `mcp__signalpilot__explore_column` — distinct values for a column
- `mcp__signalpilot__query_database` — execute SQL queries (read-only)
- `mcp__signalpilot__validate_sql` — check SQL syntax without executing
- `mcp__signalpilot__find_join_path` — find how to join two tables
- `mcp__signalpilot__schema_link` — find tables relevant to a question

## Key Rules
{rules}

## Output Requirements
- Save your final SQL query to `result.sql` (use Write tool)
- Save the query result as CSV to `result.csv` (use Write tool)
- Do NOT modify the database — read-only queries only
- The CSV must include a header row with column names

## Workflow
1. Explore the schema to understand available tables and columns
2. Write a SQL query that answers the task question
3. Execute: `mcp__signalpilot__query_database` with `connection_name="{connection_name}"`
4. Verify the result is sensible (row count, column values)
5. Write final SQL to `result.sql`
6. Write final CSV result to `result.csv`
"""
    (work_dir / "CLAUDE.md").write_text(content)
    log(f"Wrote SQL CLAUDE.md to {work_dir}")
