"""Working-directory lifecycle helpers for the dbt benchmark runners."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from .logging import log
from .paths import EXAMPLES_DIR, PROJECT_ROOT, SKILLS_SRC, WORK_DIR

if TYPE_CHECKING:
    from .suite import DBBackend, SuiteConfig


def write_workdir_env(work_dir: Path, backend: "DBBackend", task: dict) -> None:
    """Write a metadata-only .env into the agent workdir.

    Contains DB type and connection metadata so the agent can reference them.
    Never writes credentials (tokens, passwords, service account content).
    """
    from .suite import DBBackend as _DBBackend

    try:
        lines: list[str] = []

        if backend == _DBBackend.SQLITE:
            db_name: str = task.get("db", task.get("db_id", ""))
            if not db_name:
                log("write_workdir_env: missing 'db'/'db_id' for SQLite task", "WARN")
                return
            db_path = str(work_dir / f"{db_name}.sqlite")
            lines = [
                "DB_TYPE=sqlite",
                f"DB_PATH={db_path}",
                f"DATABASE_URL=sqlite:///{db_path}",
            ]

        elif backend == _DBBackend.SNOWFLAKE:
            database: str = task.get("db_id", task.get("db", task.get("database", "")))
            schema: str = task.get("schema", task.get("schema_name", "PUBLIC"))
            if not database:
                log("write_workdir_env: missing 'db_id'/'db'/'database' for Snowflake task", "WARN")
                return
            lines = [
                "DB_TYPE=snowflake",
                f"DATABASE_NAME={database}",
                f"SCHEMA_NAME={schema}",
            ]

        elif backend == _DBBackend.BIGQUERY:
            project: str = task.get("project_id", task.get("project", ""))
            dataset: str = task.get("dataset", task.get("schema", ""))
            if not project:
                project = "spider2-public-data"
            if not dataset:
                dataset = task.get("db", "")
            if not dataset:
                log("write_workdir_env: missing dataset for BigQuery task", "WARN")
                return
            lines = [
                "DB_TYPE=bigquery",
                f"DATABASE_NAME={project}",
                f"SCHEMA_NAME={dataset}",
            ]

        else:
            log(f"write_workdir_env: unsupported backend '{backend}'", "WARN")
            return

        env_path = work_dir / ".env"
        env_path.write_text("\n".join(lines) + "\n")
        log(f"Wrote metadata .env to {env_path}")

    except Exception as e:
        log(f"write_workdir_env failed (non-fatal): {e}", "WARN")


def force_rmtree(path: Path) -> None:
    """Remove a directory tree, handling Windows read-only permission errors."""

    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)

    shutil.rmtree(path, onerror=on_error)


def prepare_workdir(instance_id: str, data_dir: Path | None = None) -> Path:
    """Copy the task's dbt project into a fresh working directory under _dbt_workdir/."""
    examples = (data_dir / "examples") if data_dir else EXAMPLES_DIR
    src = examples / instance_id
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


def prepare_sql_workdir(
    instance_id: str,
    config: "SuiteConfig",
    task: dict,
    backend: "DBBackend | None" = None,
    skill_names: "tuple[str, ...] | None" = None,
) -> Path:
    """Create a fresh SQL working directory for the given task.

    Unlike prepare_workdir (DBT), no project template is copied — the directory starts empty.
    Files placed: .mcp.json, .claude/skills/<skill>/, optional external knowledge docs,
    optional schema files. CLAUDE.md is written separately by write_sql_claude_md.
    """
    from .suite import BenchmarkSuite

    work_dir = config.work_dir / instance_id
    if work_dir.exists():
        force_rmtree(work_dir)
    work_dir.mkdir(parents=True)
    log(f"Created SQL workdir: {work_dir}")

    # Copy .mcp.json so Claude Code discovers SignalPilot MCP tools
    mcp_json_src = PROJECT_ROOT / ".mcp.json"
    if mcp_json_src.exists():
        shutil.copy2(mcp_json_src, work_dir / ".mcp.json")
        log("Copied .mcp.json for MCP tool discovery")

    # Copy only the requested skills into .claude/skills/
    # skill_names parameter takes precedence over config.skills (backend-specific override).
    # config.skills is the fallback for backward compatibility.
    skills_dst = work_dir / ".claude" / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    skills_to_copy: tuple[str, ...] | list[str]
    if skill_names is not None:
        skills_to_copy = skill_names
        log(f"Using backend-specific skills: {list(skill_names)}")
    else:
        skills_to_copy = config.skills
    for skill_name in skills_to_copy:
        skill_src = SKILLS_SRC / skill_name
        if skill_src.exists():
            shutil.copytree(
                skill_src,
                skills_dst / skill_name,
                dirs_exist_ok=True,
            )
            log(f"Copied skill '{skill_name}' -> {skills_dst / skill_name}")
        else:
            log(f"Skill directory not found: {skill_src}", "WARN")

    # Copy external knowledge document if present
    external_knowledge = task.get("external_knowledge")
    if external_knowledge:
        doc_src = config.data_dir / "resource" / "documents" / external_knowledge
        if doc_src.exists():
            shutil.copy2(doc_src, work_dir / external_knowledge)
            log(f"Copied external knowledge: {doc_src.name}")
        else:
            log(f"External knowledge document not found: {doc_src}", "WARN")

    # Copy database schema files
    resource_db_dir = config.data_dir / "resource" / "databases"
    schema_dst = work_dir / "schema"

    if config.suite == BenchmarkSuite.SNOWFLAKE:
        db_id = task.get("db_id", "")
        if db_id:
            db_schema_src = resource_db_dir / db_id
            if db_schema_src.exists():
                schema_dst.mkdir(parents=True, exist_ok=True)
                shutil.copytree(db_schema_src, schema_dst, dirs_exist_ok=True)
                log(f"Copied schema files for '{db_id}' -> {schema_dst}")
    else:
        # Spider2-Lite: check sqlite/snowflake/bigquery subdirs for task's db name
        db_name = task.get("db", "")
        if db_name:
            for db_type in ("sqlite", "snowflake", "bigquery"):
                type_dir = resource_db_dir / db_type
                db_schema_src = type_dir / db_name
                if db_schema_src.exists():
                    schema_dst.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(db_schema_src, schema_dst, dirs_exist_ok=True)
                    log(f"Copied schema files for '{db_name}' ({db_type}) -> {schema_dst}")
                    break

    # Set up SQLite database: prefer pre-downloaded .sqlite file, fall back to building from JSON+DDL
    if backend is not None:
        from .suite import DBBackend as _DBBackend

        if backend == _DBBackend.SQLITE:
            db_name = task.get("db", "")
            if db_name:
                sqlite_path = work_dir / f"{db_name}.sqlite"
                # Check for pre-downloaded .sqlite file first
                localdb_dir = config.data_dir / "resource" / "databases" / "spider2-localdb"
                prebuilt = localdb_dir / f"{db_name}.sqlite"
                if prebuilt.exists():
                    shutil.copy2(prebuilt, sqlite_path)
                    log(f"Copied pre-built SQLite DB '{db_name}' -> {sqlite_path}")
                else:
                    # Fall back to building from JSON+DDL resource files
                    from .sqlite_builder import build_sqlite_db

                    resource_db_dir = config.data_dir / "resource" / "databases" / "sqlite"
                    try:
                        build_sqlite_db(db_name, resource_db_dir, sqlite_path)
                    except Exception as e:
                        log(f"Failed to build SQLite DB '{db_name}': {e}", "ERROR")

    # Initialize a git repo so Claude Code discovers skills in .claude/skills/
    subprocess.run(["git", "init"], cwd=str(work_dir), capture_output=True)

    return work_dir


def write_sql_claude_md(
    work_dir: Path,
    instance_id: str,
    instruction: str,
    backend: "DBBackend",
    connection_name: str,
) -> None:
    """Write CLAUDE.md with task instructions for SQL benchmark tasks."""
    content = f"""# Spider2 SQL Benchmark Task: {instance_id}

## Your Task
{instruction}

## Database Access
The database is registered in SignalPilot as connection `{connection_name}`.
Database type: `{backend.value}`

Use SignalPilot MCP tools to explore and query the database:
- `mcp__signalpilot__list_tables` — list all tables with column names and row counts (START HERE)
- `mcp__signalpilot__describe_table` — column details for a table
- `mcp__signalpilot__explore_table` — deep-dive with sample values
- `mcp__signalpilot__query_database` — run SQL queries (read-only)
- `mcp__signalpilot__schema_ddl` — full schema as DDL (CREATE TABLE statements)
- `mcp__signalpilot__schema_link` — find tables relevant to a question
- `mcp__signalpilot__find_join_path` — find how to join two tables
- `mcp__signalpilot__explore_column` — distinct values for a column
- `mcp__signalpilot__validate_sql` — check SQL syntax without executing
- `mcp__signalpilot__debug_cte_query` — test CTE steps independently
- `mcp__signalpilot__explain_query` — get execution plan
- `mcp__signalpilot__schema_overview` — whole-database overview (slow — prefer list_tables instead)
"""

    # Add external knowledge section if non-CLAUDE.md .md files exist
    md_docs = [f for f in work_dir.glob("*.md") if f.name != "CLAUDE.md"]
    if md_docs:
        content += "\n## External Knowledge\n"
        content += "Read the following files in this directory for domain context:\n"
        for doc in md_docs:
            content += f"- `{doc.name}`\n"

    # Add schema section if schema/ directory exists
    schema_dir = work_dir / "schema"
    if schema_dir.exists():
        content += "\n## Database Schema\n"
        content += "Schema definition files are in the `schema/` directory.\n"
        content += "- `DDL.csv` — CREATE TABLE statements for all tables\n"
        content += "- `{table_name}.json` — column names, types, descriptions, and sample rows\n"
        content += "Read the JSON files for column descriptions and sample data BEFORE calling MCP tools.\n"
        content += "This saves tool calls — you already have the schema locally.\n"

    # Add SQLite database section if a .sqlite file was built into work_dir
    sqlite_files = list(work_dir.glob("*.sqlite"))
    if sqlite_files:
        db_file_name = sqlite_files[0].name
        content += "\n## SQLite Database\n"
        content += f"The SQLite database file `{db_file_name}` is available for direct local access.\n"
        content += "For queries returning more than 50 rows, query the local file directly using Python sqlite3 or the sqlite3 CLI, then save results to result.csv.\n"
        content += f"- CLI: `sqlite3 {db_file_name} \"SELECT ...\"` or `sqlite3 {db_file_name}` for interactive mode\n"
        content += f"- Python: `import sqlite3; conn = sqlite3.connect('{db_file_name}'); ...`\n"
        content += f"For smaller queries and schema discovery, use MCP tools with connection_name=\"{connection_name}\".\n"

    content += """
## Environment Metadata
A `.env` file in this directory contains DB metadata (type, database name, schema) for reference.
Use MCP tools listed above for schema discovery and validation.

## Key Rules
- This is a READ-ONLY task — do NOT insert, update, delete, or create objects
- Write your final SQL query to `result.sql` in this directory
- Write your final result as a CSV to `result.csv` in this directory
- Use the connection name shown above for all MCP tool calls
"""

    (work_dir / "CLAUDE.md").write_text(content)
    log(f"Wrote CLAUDE.md to {work_dir}")


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
