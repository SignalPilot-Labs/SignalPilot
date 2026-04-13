"""Working-directory lifecycle helpers for the dbt benchmark runners."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from .logging import log
from .paths import EXAMPLES_DIR, PROJECT_ROOT, SKILLS_SRC, WORK_DIR


def force_rmtree(path: Path) -> None:
    """Remove a directory tree, handling Windows read-only permission errors."""

    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)

    shutil.rmtree(path, onerror=on_error)


def prepare_workdir(instance_id: str) -> Path:
    """Copy the task's dbt project into a fresh working directory under _dbt_workdir/."""
    src = EXAMPLES_DIR / instance_id
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
