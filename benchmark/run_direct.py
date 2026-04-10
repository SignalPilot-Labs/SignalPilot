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
import asyncio
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
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)
from claude_agent_sdk._errors import ProcessError, ClaudeSDKError

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Ensure dbt (pip-installed to ~/.local/bin) is on PATH for agent subprocesses
_local_bin = os.path.expanduser("~/.local/bin")
if _local_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _local_bin + ":" + os.environ.get("PATH", "")

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


# ── MCP config loader ──────────────────────────────────────────────────────────

def _load_mcp_servers() -> dict:
    """Load MCP server configs from MCP_CONFIG, stripping unsupported 'cwd' key."""
    with open(MCP_CONFIG) as f:
        raw = json.load(f)
    servers = raw.get("mcpServers", {})
    result: dict = {}
    for name, config in servers.items():
        entry = {k: v for k, v in config.items() if k != "cwd"}
        result[name] = entry
    return result


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

    # Copy .mcp.json so Claude Code discovers SignalPilot MCP tools
    mcp_json_src = Path(__file__).parent.parent / ".mcp.json"
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


def _scan_current_date_models(work_dir: Path) -> list[tuple[str, int, str]]:
    """Scan models/ for .sql files that reference current_date/now() and return matches."""
    import re
    matches = []
    models_dir = work_dir / "models"
    if not models_dir.exists():
        return matches
    for sql_file in models_dir.rglob("*.sql"):
        try:
            content = sql_file.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                if re.search(r'\bcurrent_date\b|\bCURRENT_DATE\b|\bnow\(\)|\bcurrent_timestamp\b|\bCURRENT_TIMESTAMP\b|\bcurrent_timestamp_backcompat\b|\bgetdate\(\)', line, re.IGNORECASE):
                    rel_path = str(sql_file.relative_to(work_dir))
                    matches.append((rel_path, i, line.strip()))
        except Exception:
            pass
    return matches



def _rewrite_inner_joins(work_dir: Path, task_instruction: str) -> list[str]:
    """Rewrite INNER JOIN to LEFT JOIN in all non-ephemeral SQL model files.

    Returns list of relative paths (relative to work_dir) of files modified.
    Skips rewriting entirely if the task instruction contains explicit exclusion language.
    """
    skip_dirs = (".claude", "dbt_packages", "target", "macros")
    exclusion_phrases = (
        "only ",
        "with orders",
        "with at least",
        "who have",
        "who has",
        "that have",
        "exclude",
        "excluding",
        "due to ",
        "must have",
        "require",
        "filter to",
        "restrict to",
        "limited to",
    )
    inner_join_pattern = re.compile(r'\bINNER\s+JOIN\b', re.IGNORECASE)

    instruction_lower = task_instruction.lower()
    if any(phrase in instruction_lower for phrase in exclusion_phrases):
        log("INNER JOIN rewrite skipped — task has explicit exclusion language")
        return []

    modified: list[str] = []
    models_dir = work_dir / "models"
    if not models_dir.is_dir():
        return modified
    for sql_file in models_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in skip_dirs):
            continue
        try:
            content = sql_file.read_text()
            if content.strip().startswith("{{ config(materialized='ephemeral') }}"):
                continue
            matches = inner_join_pattern.findall(content)
            if not matches:
                continue
            new_content = inner_join_pattern.sub('LEFT JOIN', content)
            sql_file.write_text(new_content)
            rel_path = str(sql_file.relative_to(work_dir))
            modified.append(rel_path)
            log(f"[INFO] JOIN-FIX: {rel_path} — replaced {len(matches)} INNER JOIN(s) with LEFT JOIN")
        except Exception as exc:
            rel_path = str(sql_file.relative_to(work_dir))
            log(f"Warning: JOIN-FIX skipped {rel_path}: {exc}", "WARN")
    return modified


def _strip_speculative_filters(work_dir: Path, task_instruction: str) -> list[str]:
    """Remove WHERE/HAVING equality filters on string literals not present in the task instruction.

    Returns list of (relative_path, removed_condition_string) tuples as strings.
    Only removes = 'string_literal' equality conditions. Never touches numeric equality,
    NULL checks, date strings, IN lists, LIKE clauses, or != / <> operators.
    """
    skip_dirs = (".claude", "dbt_packages", "target", "macros")
    # Matches: WHERE/AND/OR/HAVING followed by identifier = 'literal'
    filter_pattern = re.compile(
        r'(?P<keyword>WHERE|AND|OR|HAVING)\s+(?P<col>\w+)\s*=\s*\'(?P<literal>[^\']+)\'',
        re.IGNORECASE | re.MULTILINE,
    )
    date_pattern = re.compile(r'\d{4}-\d{2}-\d{2}')
    # Detects an empty WHERE/HAVING clause (only whitespace before GROUP/ORDER/HAVING/LIMIT/end)
    empty_where_pattern = re.compile(
        r'\b(WHERE|HAVING)\s*(?=GROUP\s+BY|ORDER\s+BY|LIMIT|UNION|$)',
        re.IGNORECASE | re.MULTILINE,
    )

    instruction_lower = task_instruction.lower()
    removed_items: list[str] = []

    # Pattern to detect comment regions (line comments and block comments)
    line_comment_pattern = re.compile(r'--.*$', re.MULTILINE)
    block_comment_pattern = re.compile(r'/\*.*?\*/', re.DOTALL)
    # Pattern to clean up WHERE AND/OR → WHERE (after removing first condition)
    dangling_and_or = re.compile(r'\b(WHERE|HAVING)\s+(AND|OR)\b', re.IGNORECASE)

    models_dir = work_dir / "models"
    if not models_dir.is_dir():
        return removed_items

    for sql_file in models_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in skip_dirs):
            continue
        try:
            content = sql_file.read_text()
            if content.strip().startswith("{{ config(materialized='ephemeral') }}"):
                continue

            file_modified = False
            working_content = content
            rel_path = str(sql_file.relative_to(work_dir))

            # Build set of comment character positions to skip matches inside comments
            comment_positions: set[int] = set()
            for cm in line_comment_pattern.finditer(content):
                comment_positions.update(range(cm.start(), cm.end()))
            for cm in block_comment_pattern.finditer(content):
                comment_positions.update(range(cm.start(), cm.end()))

            # Collect speculative matches first (in reverse order to preserve offsets)
            speculative: list[re.Match[str]] = []
            for m in filter_pattern.finditer(working_content):
                # Skip matches inside comments
                if m.start() in comment_positions:
                    continue
                literal = m.group('literal')
                # Safety constraints: skip date strings
                if date_pattern.search(literal):
                    continue
                # Skip if literal appears in task instruction
                if literal.lower() in instruction_lower:
                    continue
                speculative.append(m)

            if not speculative:
                continue

            # Process in reverse order to keep string offsets valid
            for m in reversed(speculative):
                keyword = m.group('keyword').upper()
                col = m.group('col')
                literal = m.group('literal')
                full_match = m.group(0)

                if keyword in ('AND', 'OR', 'HAVING'):
                    # Drop the entire condition fragment (keyword + col = 'val')
                    replacement = ''
                elif keyword == 'WHERE':
                    # Keep WHERE, remove the condition part
                    # WHERE col = 'val' → WHERE (cleanup handles dangling WHERE/AND)
                    replacement = 'WHERE '
                else:
                    replacement = ''

                new_content = working_content[:m.start()] + replacement + working_content[m.end():]
                # Validate: check parens balance hasn't worsened vs current working state
                if new_content.count('(') != working_content.count('(') or new_content.count(')') != working_content.count(')'):
                    log(f"Warning: FILTER-FIX skipped {rel_path} — paren imbalance after removing {full_match!r}", "WARN")
                    continue

                working_content = new_content
                file_modified = True
                condition_str = f"{keyword} {col} = '{literal}'"
                removed_items.append(f"({rel_path}, {condition_str})")
                log(f"[INFO] FILTER-FIX: {rel_path} — removed speculative filter: {condition_str}")

            if not file_modified:
                continue

            # Clean up WHERE AND/OR → WHERE and HAVING AND/OR → HAVING
            working_content = dangling_and_or.sub(r'\1', working_content)
            # Clean up any dangling WHERE/HAVING clause left with no conditions
            working_content = empty_where_pattern.sub('', working_content)

            # Final safety check: if result looks structurally broken, abort
            if working_content.count('(') != working_content.count(')'):
                log(f"Warning: FILTER-FIX aborted for {rel_path} — result has unbalanced parens", "WARN")
                continue

            sql_file.write_text(working_content)
        except Exception as exc:
            rel_path = str(sql_file.relative_to(work_dir))
            log(f"Warning: FILTER-FIX skipped {rel_path}: {exc}", "WARN")

    return removed_items


def _run_post_agent_sql_fixes(
    work_dir: Path,
    task_instruction: str,
    eval_critical_models: set[str],
) -> None:
    """Run deterministic SQL rewrites on generated model files before the final dbt run."""
    log_separator("Post-agent SQL fixes (deterministic)")
    join_fixes = _rewrite_inner_joins(work_dir, task_instruction)
    # Filter stripping disabled — too many false positives on legitimate staging filters.
    # The JOIN rewriter alone covers the highest-ROI pattern.
    if join_fixes:
        log(f"SQL fixes applied: {len(join_fixes)} join rewrite(s)")
    else:
        log("No post-agent SQL fixes needed")


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


def _extract_model_descriptions(work_dir: Path) -> dict[str, str]:
    """Extract model description text from YML files. Returns {model_name: description}."""
    import yaml

    result: dict[str, str] = {}
    for ext in ("*.yml", "*.yaml"):
        for yml_file in work_dir.rglob(ext):
            if any(skip in str(yml_file) for skip in (".claude", "dbt_packages", "target")):
                continue
            try:
                data = yaml.safe_load(yml_file.read_text())
                if data and "models" in data:
                    for model in data["models"]:
                        name = model.get("name")
                        desc = model.get("description", "").strip()
                        if name and desc:
                            # Truncate to first 200 chars to avoid prompt bloat
                            result[name] = desc[:200].replace("\n", " ")
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

    db_path_obj = _find_result_db(work_dir)
    if not db_path_obj:
        return []

    try:
        con = duckdb.connect(database=str(db_path_obj), read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return tables
    except Exception:
        return []


def _get_table_row_counts(work_dir: Path) -> dict[str, int]:
    """Return a mapping of table name -> row count from the task's DuckDB file.

    Returns empty dict if DB is missing, locked, or duckdb is unavailable.
    """
    try:
        import duckdb
    except ImportError:
        return {}

    db_path_obj = _find_result_db(work_dir)
    if not db_path_obj:
        return {}

    db_path = str(db_path_obj)
    try:
        con = duckdb.connect(database=db_path, read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        counts: dict[str, int] = {}
        for table in tables:
            row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            if row is not None:
                counts[table] = int(row[0])
        con.close()
        return counts
    except Exception:
        return {}


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
    model_descriptions = _extract_model_descriptions(work_dir)
    col_spec_lines = []
    for model_name in sorted(missing_priority | (stub_models & eval_critical_models)):
        desc = model_descriptions.get(model_name, "")
        desc_str = f" | DESC: {desc}" if desc else ""
        if model_name in model_columns:
            col_spec_lines.append(f"  {model_name}: {', '.join(model_columns[model_name])}{desc_str}")
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
You have a budget of {max_turns} turns. Plan accordingly — do not exhaust turns on exploration.

TASK: {instruction}

DATABASE: SignalPilot connection '{instance_id}' (DuckDB). Use mcp__signalpilot__* tools.

MISSING SQL MODELS — PRIORITY (evaluated, must complete): {priority_str}
MISSING SQL MODELS — OTHER (write if time permits): {other_missing_str}
INCOMPLETE SQL (stubs — must rewrite): {stubs_str}
EXISTING SQL MODELS: {existing_str}

MODEL DEPENDENCIES (write dependencies first):
{deps_str}

REQUIRED COLUMNS FOR PRIORITY MODELS:
{col_spec_str}

DO THIS IN ORDER:
1. {'Run: dbt deps' if has_packages_yml else 'SKIP dbt deps — no packages.yml, packages are pre-installed. NEVER run dbt deps on this project.'}
2. mcp__signalpilot__list_tables connection_name="{instance_id}"
2b. mcp__signalpilot__get_date_boundaries connection_name="{instance_id}"
    - The tool marks the correct table with "← USE THIS" — use that table's max date as the spine endpoint.
    - The spine endpoint is ALWAYS the primary fact/event table's max date (orders, transactions, events, sessions, activities, etc.).
    - Identify the fact table as: the table with the most rows, OR the primary entity the task references.
    - NEVER use GLOBAL MAX DATE — dimension, lookup, and reference tables often have later dates and must NOT set the endpoint.
    - Never use current_date, now(), or current_timestamp.
3. Explore at most 2 source tables with explore_table. Stop exploring — begin writing SQL.
4. For each priority model in dependency order — complete ALL sub-steps before moving to the next model:
   a. Read its YML file. If dbt_packages/ exists, also read related package models (dbt_packages/*/models/**/*.sql) — they provide pre-built columns you can ref() instead of re-deriving.
   b. Write the .sql file
      - NEVER modify .yml or .yaml files — only create/edit .sql files
      - Column names in YML are exact — alias SELECT output to match them character-for-character
      - Use ref() for upstream models, source() for raw tables
      - If a ref('model_name') fails because no .sql file exists BUT the table already exists in the database,
        create an ephemeral wrapper: {{ config(materialized='ephemeral') }} SELECT * FROM model_name
        This bridges pre-existing tables to dbt's ref() system without altering the database.
      - DEFAULT to LEFT JOIN for all JOINs. Only use INNER JOIN if the task explicitly says to exclude non-matching rows (e.g., "customers WITH orders", "only users who have", "exclude rows without") AND you have called compare_join_types. Phrases like "based on", "for each X in Y", "calculates X from Y" are NOT exclusion — they describe the calculation scope, keep LEFT JOIN.
      - When combining similar source tables (e.g., comedies + dramas + docuseries), prefer UNION (dedup) over UNION ALL if sources may contain duplicate/overlapping rows. UNION ALL keeps all rows including duplicates; UNION deduplicates. Check source data for identical rows before deciding.
      - For monetary columns (spend, cost, price, amount): source data may store charges as negative values (accounting convention). For account-level summary/overview models, use ROUND(SUM(ABS(price)), 2) for spend totals. For detail/per-entity models, keep the original sign from source.
      - CRITICAL: Do NOT use COALESCE(col, 0) on LEFT JOIN results unless the YML description explicitly says "treat nulls as zero". When a date spine LEFT JOINs to event counts, days with no events should remain NULL, not 0. The evaluator distinguishes NULL from 0.
      - ROLLING WINDOW / MoM / WoW models: If YML description says "rolling window", "MoM", "WoW", or "comparison" AND unique_key includes date×entity — the model outputs ONE date (the latest) per entity, NOT all dates. Add: WHERE date_col = (SELECT MAX(date_col) FROM source).
      - Do NOT cast ID columns to different types. If the source column is INTEGER, keep it INTEGER in the output — do not CAST to VARCHAR.
      - ROW_NUMBER() must always have a fully deterministic ORDER BY. Add enough columns to break all ties (e.g., ORDER BY person_id, start_date, source_value). Non-deterministic ordering causes different IDs across runs.
      - Do NOT add WHERE/HAVING filters unless the task description or YML explicitly requires excluding rows. Common mistakes: filtering by role/type/status based on table names (e.g., WHERE role='ACTOR' because the table is named 'actor_rating'), filtering NULLs from UNIONs when only some columns are NULL, adding HAVING to exclude NULLs. A row with some NULL columns is real data — keep it.
   c. Run: dbt run --select <model>
      If dbt fails: use mcp__signalpilot__dbt_error_parser with the error text, fix SQL, re-run.
   d. Run BOTH of these after every dbt run (mandatory):
      mcp__signalpilot__validate_model_output connection_name="{instance_id}" model_name="<model>"
      mcp__signalpilot__audit_model_sources connection_name="{instance_id}" model_name="<model>" source_tables="<comma-separated upstream tables>"
      → 0 rows = fix JOIN/WHERE. Fan-out ratio > 2x = pre-aggregate or ROW_NUMBER() dedup. Over-filter < 0.5 = INNER→LEFT JOIN or WHERE too restrictive.
   e. Run: mcp__signalpilot__check_model_schema connection_name="{instance_id}" model_name="<model>" yml_columns="<exact comma-separated cols from YML>"
      → MISSING columns = add to SQL, go back to step c. Do NOT proceed until all columns match.
   MODEL IS COMPLETE only when c + d + e all pass. Then move to the next model.
5. mcp__signalpilot__query_database connection_name="{instance_id}" sql="SHOW TABLES"
   → every eval-critical model name must appear exactly as written
{'- ' + packages_hint.lstrip() if packages_hint else ''}"""

    # Scan for current_date in existing models and warn the agent
    current_date_hits = _scan_current_date_models(work_dir)
    if current_date_hits:
        warning_lines = ["", "⚠ CRITICAL: These existing .sql files use current_date/current_timestamp/now() and MUST be edited:"]
        for rel_path, line_no, line_text in current_date_hits:
            warning_lines.append(f"  {rel_path}:{line_no}: {line_text}")
            model_name = Path(rel_path).stem
            if model_name in db_tables:
                warning_lines.append(f"  NOTE: {model_name} already has pre-computed data in the database.")
                warning_lines.append(f"  Query its max date with: SELECT MAX(<date_col>) FROM {model_name}")
                warning_lines.append("  Use that value as the replacement for current_date in this file — NOT the fact table max from get_date_boundaries.")
                warning_lines.append("  (Replace <date_col> with the actual date column name you see in the model's SELECT list.)")
        warning_lines.append("After calling get_date_boundaries in step 2b, IMMEDIATELY edit ALL these files:")
        warning_lines.append("  Replace current_date, CURRENT_DATE, current_timestamp, current_timestamp_backcompat(), now(), getdate() → CAST('<MAX_DATE>' AS DATE) or CAST('<MAX_DATE>' AS TIMESTAMP)")
        warning_lines.append("  where <MAX_DATE> is the primary fact/event table's max date from get_date_boundaries (look for the '← USE THIS' marker).")
        warning_lines.append("  For dbt macros like dbt.current_timestamp_backcompat(): replace the entire macro call with the cast.")
        warning_lines.append("Do NOT skip this — it is the #1 cause of row count and value mismatches.")
        prompt += "\n".join(warning_lines)

    # Add eval-critical table names
    if eval_critical_models:
        crit_names = ", ".join(sorted(eval_critical_models))
        prompt += f"\n\nEVAL-CRITICAL TABLES (must exist with these exact names): {crit_names}"

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

    table_counts = _get_table_row_counts(work_dir)
    if table_counts:
        counts_lines = [f"  {name}: {count:,} rows" for name, count in sorted(table_counts.items())]
        prompt += "\n\nSOURCE TABLE CARDINALITIES (row counts of tables already in the DuckDB file):\n"
        prompt += "\n".join(counts_lines)
        prompt += "\n- These are INPUT table sizes, not expected output sizes."

    checkpoint_turn = min(6, max_turns // 3)
    exploration_end = min(4, max_turns // 4)
    priority_deadline = max(4, max_turns - 8)

    prompt += f"\n\nBudget: explore in turns 1-{exploration_end}, write priority models by turn {priority_deadline}, verify after."

    return prompt


# ── Agent runner ───────────────────────────────────────────────────────────────

SKILL_TOOL_NAMES = ("dbt-workflow", "dbt-verification", "dbt-debugging", "duckdb-sql")


async def _run_sdk_agent(
    prompt: str,
    work_dir: Path,
    model: str,
    max_turns: int,
    timeout: int,
    label: str = "agent",
    max_retries: int = 3,
) -> dict:
    """Run the Claude Agent SDK with retry on 529/overload errors."""
    options = ClaudeAgentOptions(
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        cwd=str(work_dir),
        mcp_servers=_load_mcp_servers(),
        debug_stderr=True,
    )

    log_separator(f"AGENT model={model}  max_turns={max_turns}  timeout={timeout}s  label={label}")

    for attempt in range(1, max_retries + 1):
        messages: list[str] = []
        tool_calls: list[dict] = []
        turn_count = 0
        start_time = time.monotonic()
        success = False

        try:
            async for message in query(prompt=prompt, options=options):
                elapsed = time.monotonic() - start_time

                if isinstance(message, AssistantMessage):
                    turn_count += 1
                    log(f"─── Turn {turn_count} ({elapsed:.1f}s) ───")
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            for line in block.text.split("\n"):
                                log(f"[agent] {line}")
                            messages.append(block.text)
                        elif isinstance(block, ToolUseBlock):
                            tool_input_str = json.dumps(block.input, ensure_ascii=False)
                            truncated = tool_input_str[:500] + "..." if len(tool_input_str) > 500 else tool_input_str
                            log(f"[tool_use] {block.name}")
                            log(f"  input: {truncated}")
                            tool_calls.append({"name": block.name, "input": block.input, "turn": turn_count})
                            if block.name in SKILL_TOOL_NAMES:
                                log(f"[skill] Agent invoked /{block.name}")
                            elif block.name == "Skill" and isinstance(block.input, dict):
                                skill_name = block.input.get("skill", "unknown")
                                log(f"[skill] Agent invoked /{skill_name}")
                        elif isinstance(block, ToolResultBlock):
                            result_str = str(block.content) if hasattr(block, "content") else str(block)
                            truncated = result_str[:1000] + "..." if len(result_str) > 1000 else result_str
                            log(f"[tool_result] {truncated}")

                elif isinstance(message, ResultMessage):
                    elapsed = time.monotonic() - start_time
                    log(f"AGENT FINISHED after {turn_count} turns, {elapsed:.1f}s")
                    if hasattr(message, "cost_usd"):
                        log(f"  Cost: ${getattr(message, 'cost_usd', 'N/A')}")
                    if hasattr(message, "usage"):
                        log(f"  Usage: {getattr(message, 'usage', 'N/A')}")
                    success = True

        except ProcessError as e:
            err_str = str(e)
            stderr_str = getattr(e, "stderr", "") or ""
            is_overloaded = (
                "529" in err_str or "overloaded" in err_str.lower()
                or "529" in stderr_str or "overloaded" in stderr_str.lower()
            )
            if is_overloaded:
                log(f"API overloaded ({label}, attempt {attempt}/{max_retries}): {err_str[:200]}", "WARN")
                if attempt < max_retries:
                    wait = 30 * attempt
                    log(f"Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                else:
                    log(f"API overloaded after {max_retries} retries ({label}) — giving up", "ERROR")
                    return {"success": False, "messages": messages, "tool_calls": tool_calls, "turns": turn_count, "elapsed": time.monotonic() - start_time}
            else:
                log(f"Agent ProcessError ({label}): {e}", "ERROR")
                return {"success": False, "messages": messages, "tool_calls": tool_calls, "turns": turn_count, "elapsed": time.monotonic() - start_time}

        except ClaudeSDKError as e:
            err_str = str(e)
            is_overloaded = "529" in err_str or "overloaded" in err_str.lower()
            if is_overloaded:
                log(f"API overloaded ({label}, attempt {attempt}/{max_retries}): {err_str[:200]}", "WARN")
                if attempt < max_retries:
                    wait = 30 * attempt
                    log(f"Retrying in {wait}s...")
                    await asyncio.sleep(wait)
                    continue
                else:
                    log(f"API overloaded after {max_retries} retries ({label}) — giving up", "ERROR")
                    return {"success": False, "messages": messages, "tool_calls": tool_calls, "turns": turn_count, "elapsed": time.monotonic() - start_time}
            else:
                log(f"Agent ClaudeSDKError ({label}): {e}", "ERROR")
                return {"success": False, "messages": messages, "tool_calls": tool_calls, "turns": turn_count, "elapsed": time.monotonic() - start_time}

        except Exception as e:
            err_str = str(e)
            is_overloaded = "529" in err_str or "overloaded" in err_str.lower()
            if is_overloaded and attempt < max_retries:
                log(f"API overloaded ({label}, attempt {attempt}/{max_retries}): {err_str[:200]}", "WARN")
                wait = 30 * attempt
                log(f"Retrying in {wait}s...")
                await asyncio.sleep(wait)
                continue
            # If the agent had already finished (success=True from ResultMessage),
            # treat the exit error as non-fatal — work was completed.
            if success:
                log(f"Agent completed but SDK raised on exit ({label}): {err_str[:200]}", "WARN")
            else:
                log(f"Agent error ({label}): {e}", "ERROR")
                return {"success": False, "messages": messages, "tool_calls": tool_calls, "turns": turn_count, "elapsed": time.monotonic() - start_time}

        elapsed = time.monotonic() - start_time
        return {"success": success, "messages": messages, "tool_calls": tool_calls, "turns": turn_count, "elapsed": elapsed}

    # Should not reach here, but guard for type checker
    return {"success": False, "messages": [], "tool_calls": [], "turns": 0, "elapsed": 0.0}


async def run_agent(
    instance_id: str,
    instruction: str,
    work_dir: Path,
    model: str,
    max_turns: int,
    eval_critical_models: set[str],
) -> bool:
    """Run the Claude Agent SDK in the work directory."""
    log_separator(f"AGENT  model={model}  max_turns={max_turns}  instance={instance_id}")

    prompt = build_agent_prompt(instance_id, instruction, work_dir, eval_critical_models, max_turns=max_turns)
    log(f"Prompt length: {len(prompt)} chars")

    result = await _run_sdk_agent(prompt, work_dir, model, max_turns, timeout=900, label="main-agent")

    transcript_path = work_dir / "agent_output.json"
    transcript_path.write_text(json.dumps({
        "tool_calls": result["tool_calls"],
        "messages": result["messages"],
        "turns": result["turns"],
    }))

    return result["success"]


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


def _find_result_db(project_dir: Path, expected_name: str | None = None) -> Path | None:
    """Return the best candidate result DuckDB file in project_dir.

    Filters out locked/backup files, then prefers the file matching expected_name
    (if given), otherwise returns the largest file by size.
    """
    _EXCLUDE_SUFFIXES = ("_locked", "_bak", "_backup")
    candidates = [
        p for p in project_dir.glob("*.duckdb")
        if not any(s in p.name.lower() for s in _EXCLUDE_SUFFIXES)
    ]
    if not candidates:
        return None
    if expected_name is not None:
        for p in candidates:
            if p.name == expected_name:
                return p
    return max(candidates, key=lambda p: p.stat().st_size)


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
    _path = _find_result_db(project_dir, params["gold"])
    result_db_path = str(_path) if _path else str(project_dir / params["gold"])

    condition_tabs: list[str] | None = params.get("condition_tabs")
    condition_cols: list[list[int]] | None = params.get("condition_cols")
    ignore_orders: list[bool] | None = params.get("ignore_orders")

    log(f"Gold DB:   {gold_db_path}")
    log(f"Result DB: {result_db_path}")

    if not Path(result_db_path).exists():
        return False, f"Result DB not found: {result_db_path}"
    if not Path(gold_db_path).exists():
        return False, f"Gold DB not found: {gold_db_path}"

    # Use persistent connections to avoid DuckDB WAL visibility issues
    # when opening multiple short-lived read-only connections
    gold_con = duckdb.connect(database=gold_db_path, read_only=True)
    result_con = duckdb.connect(database=result_db_path, read_only=True)

    def get_tables(con) -> list[str]:
        return [r[0] for r in con.execute("SHOW TABLES").fetchall()]

    def get_table_df(con, table_name: str):
        return con.execute(f"SELECT * FROM {table_name}").fetchdf()

    result_tables = get_tables(result_con)
    gold_tables = get_tables(gold_con)
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
            gold_df = get_table_df(gold_con, tab)
            pred_df = get_table_df(result_con, tab)
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

            def _normalize_for_compare(a, b):
                """Handle type mismatches between str↔Timestamp and str↔numeric."""
                # str vs Timestamp: compare as normalized strings
                from datetime import datetime, date
                a_is_dt = isinstance(a, (datetime, date, pd.Timestamp))
                b_is_dt = isinstance(b, (datetime, date, pd.Timestamp))
                if a_is_dt or b_is_dt:
                    try:
                        sa = str(a).rstrip('0').rstrip('.') if a_is_dt else str(a).rstrip('0').rstrip('.')
                        sb = str(b).rstrip('0').rstrip('.') if b_is_dt else str(b).rstrip('0').rstrip('.')
                        # Strip trailing .000000 type suffixes
                        for suffix in [' 00:00:00', '.0', 'T00:00:00']:
                            sa = sa.removesuffix(suffix)
                            sb = sb.removesuffix(suffix)
                        return sa == sb
                    except Exception:
                        pass
                return None  # not handled

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
                            # Try datetime/type normalization before failing
                            normalized = _normalize_for_compare(a, b)
                            if normalized is not True:
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

    gold_con.close()
    result_con.close()
    return all_match, "\n".join(details)


def _build_value_verify_prompt(
    work_dir: Path,
    instance_id: str,
    eval_critical_models: set[str],
    instruction: str,
    model_columns: dict[str, list[str]],
) -> str:
    """Build the prompt for the post-success value-verification agent."""
    sorted_models = sorted(eval_critical_models)
    model_names_str = ", ".join(sorted_models)

    col_spec_lines: list[str] = []
    for model_name in sorted_models:
        if model_name in model_columns:
            col_spec_lines.append(f"  {model_name}: {', '.join(model_columns[model_name])}")
    col_spec_str = "\n".join(col_spec_lines) if col_spec_lines else "  (read YML files for column specs)"

    return f"""SELF-VERIFICATION TASK for {instance_id}

dbt build is complete. Audit each priority model for silent failures.
Use ONLY: task's own .md files, YML specs, and your own output tables.

TASK: {instruction}

EVAL-CRITICAL MODELS: {model_names_str}

For each model, run these checks:

CHECK 1 — TABLE EXISTS:
  SHOW TABLES — confirm {model_names_str} appear.
  If missing: create SELECT * FROM ref(closest_existing_model) and run dbt run --select <name>.

CHECK 2 — COLUMN COMPLETENESS (use check_model_schema tool):
  For each model, run: mcp__signalpilot__check_model_schema(connection_name="{instance_id}", model_name="<model>", yml_columns="<comma-separated list from below>")
  The EXACT required columns (from YML) are:
{col_spec_str}
  The tool will tell you exactly which columns are MISSING, EXTRA, or have CASE MISMATCHES.
  - Any MISSING column: ADD IT to the SQL, re-run dbt.
  - Any CASE MISMATCH: RENAME to match exactly.
  - Do not accept "close enough" — column names must match the YML list precisely.

CHECK 3 — CATEGORICAL VALUE AUDIT:
  For string columns that look like status/category/type/territory:
    SELECT DISTINCT <col> FROM <model>
  Then run: find . -name "*.md" -not -path "*/dbt_packages/*" | xargs grep -l "docs"
  Read each .md file. Find {{% docs %}} blocks that list expected values for this column.
  If output values differ from doc-specified values: fix CASE WHEN and re-run dbt.

CHECK 4 — ROW COUNT VALIDATION (use validate_model_output tool):
  For each model: mcp__signalpilot__validate_model_output(connection_name="{instance_id}", model_name="<model>")
  If 0 rows: model is empty — debug JOIN/WHERE before proceeding.
  If fan-out detected: fix your JOINs.

CHECK 5 — NUMERIC SAMPLE:
  SELECT * FROM <model> LIMIT 5
  Flag: any numeric column that is 0 or NULL for ALL 5 rows (aggregation is likely wrong).
  Flag: any column identical across all 5 rows when it should vary (wrong CASE WHEN literal).

CHECK 6 — CARDINALITY SANITY (catches silent wrong-scale errors):

  a) Read the YML description for each priority model. If it says "top N" or "ranks the top N":
       SELECT COUNT(*) FROM <model>
     If count > N: a QUALIFY/WHERE rank <= N filter is missing. Add it, re-run dbt.

  b) If the description says "rolling window" or "MoM/WoW comparison" and the model has a
     surrogate_key on date×entity:
       SELECT COUNT(DISTINCT <date_col>) FROM <model>
     If distinct dates > 2: the model is building a full time-series.
     Rolling-window models with unique_key=date×entity produce ONE date per run (the latest).
     Fix: add WHERE <date_col> = (SELECT MAX(<date_col>) FROM <source>)

  c) If the model aggregates per entity (customer, driver, product):
       SELECT COUNT(*) AS model_rows FROM <model>
       SELECT COUNT(DISTINCT <entity_id>) AS entities FROM <source> [WHERE <qualifier>]
     If model_rows >> entities: JOIN fan-out — find and fix before finishing.

  d) For UNION-based models: count each branch independently:
       SELECT COUNT(*) FROM <branch_1_source> [WHERE <filter>]
       SELECT COUNT(*) FROM <branch_2_source> [WHERE <filter>]
     Sum must equal model row count. If any branch is 0 and should not be, the domain filter is wrong.

CHECK 7 — NULL / JUNK ROW FILTER:
  For UNION-based models or models sourced from scraped data (Google Sheets, CSV):
    SELECT COUNT(*) FROM <model> WHERE <primary_identifying_col> IS NULL
  If count > 0: inspect those rows. Rows where ALL columns are NULL are junk — filter them.
  But rows where only the title/name is NULL but other columns have data (genre, date, etc.)
  are likely valid data — keep those. Filter: WHERE NOT (col1 IS NULL AND col2 IS NULL AND col3 IS NULL)
  instead of WHERE title IS NOT NULL.

CHECK 8 — JOIN TYPE VERIFICATION (use compare_join_types tool):
  For each JOIN in the model SQL, call:
    mcp__signalpilot__compare_join_types(connection_name="{instance_id}", left_table="<left>", right_table="<right>", join_keys="a.<key> = b.<key>")
  If INNER JOIN drops rows that LEFT JOIN would keep, and the task doesn't explicitly exclude unmatched entities: switch to LEFT JOIN. Re-run dbt.

CHECK 9 — DUPLICATE ROW DETECTION:
  For UNION-based models, check for exact duplicate rows:
    SELECT COUNT(*) AS total, COUNT(*) - COUNT(DISTINCT <all_columns_hash>) AS duplicates
    FROM <model>
  If duplicates > 0: the UNION ALL is keeping duplicate rows. Check if the source tables have
  overlapping or identical rows. If so, consider using UNION (dedup) instead of UNION ALL.
  Also check: SELECT *, COUNT(*) as cnt FROM <model> GROUP BY ALL HAVING cnt > 1 LIMIT 5
  to see the actual duplicated rows and decide if they are real data or artifacts.

CHECK 10 — MONETARY VALUE SIGN CHECK:
  For columns with names containing 'spend', 'cost', 'price', 'amount', 'revenue', 'total':
    SELECT column_name, MIN(value), MAX(value) FROM <model>
  If a "spend" or "cost" column has all-negative values, NOTE this as a WARNING.
  Do NOT automatically fix — some models intentionally preserve negative signs (accounting convention).
  Only apply ABS() if the model is a high-level summary/overview and the column name implies a positive total (e.g., "total_messages_spend").
  For detail-level or per-entity models, keep original signs.

CHECK 11 — COALESCE AUDIT:
  Read the model SQL. If it uses COALESCE(col, 0) or COALESCE(col, '') on LEFT JOIN results:
    Query: SELECT COUNT(*) FROM <model> WHERE <coalesced_col> = 0
    If most rows are 0, the COALESCE is filling NULL join results with 0.
    This is WRONG unless the task explicitly says "treat nulls as zero".
    Fix: Remove the COALESCE — let NULLs remain. The evaluator distinguishes NULL from 0.
    Example: `coalesce(lc.leads_created, 0) as leads_created` → `lc.leads_created`

Fix any issues. Re-run dbt after fixes. Stop."""


# ── Inline async agent helpers ────────────────────────────────────────────────


async def _run_quick_fix_agent(fix_prompt: str, work_dir: Path, model: str) -> bool:
    """Run a short fix agent after a failed dbt run."""
    log("Running quick-fix agent (20 turns)...")
    result = await _run_sdk_agent(fix_prompt, work_dir, model, max_turns=20, timeout=480, label="quick-fix")
    if result["success"]:
        log("Fix agent completed")
    else:
        log("Fix agent failed")
    return result["success"]


async def _run_value_verify_agent(verify_prompt: str, work_dir: Path, model: str) -> bool:
    """Run a value-verification agent to check output correctness."""
    log("Running value-verification agent (25 turns)...")
    result = await _run_sdk_agent(verify_prompt, work_dir, model, max_turns=25, timeout=600, label="value-verify")
    log("Value-verify agent completed")
    return result["success"]


async def _run_name_fix_agent(name_fix_prompt: str, work_dir: Path, model: str) -> bool:
    """Run a short agent to fix missing table names."""
    log("Running table-name fix agent (8 turns)...")
    result = await _run_sdk_agent(name_fix_prompt, work_dir, model, max_turns=8, timeout=240, label="name-fix")
    if result["success"]:
        log("Name-fix agent completed")
    else:
        log("Name-fix agent failed")
    return result["success"]


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
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Don't reset workdir — continue from previous run's output",
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
        if args.no_reset and work_dir.exists():
            log(f"Reusing existing workdir (--no-reset): {work_dir}")
        else:
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
        _db = _find_result_db(work_dir)
        if _db:
            register_local_connection(instance_id, str(_db))
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
                max_turns = 60
            elif work_count >= 4 or (work_count >= 2 and has_macros):
                max_turns = 45
            else:
                max_turns = 30
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
        try:
            agent_ok = asyncio.run(run_agent(
                instance_id=instance_id,
                instruction=instruction,
                work_dir=work_dir,
                model=model,
                max_turns=max_turns,
                eval_critical_models=eval_critical_models,
            ))
        except Exception as e:
            log(f"Agent SDK error: {e}", "ERROR")
            agent_ok = False
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

        # Re-create ephemeral stubs for any new ref() targets the agent introduced
        created_stubs_post = _create_ephemeral_stubs(work_dir)
        if created_stubs_post:
            log(f"Post-agent ephemeral stubs created: {sorted(created_stubs_post)}")

        # Deterministic SQL fixes: rewrite INNER JOIN → LEFT JOIN, remove speculative filters
        _run_post_agent_sql_fixes(work_dir, instruction, eval_critical_models)

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

            table_counts = _get_table_row_counts(work_dir)
            if table_counts:
                counts_lines = [f"  {name}: {count:,} rows" for name, count in sorted(table_counts.items())]
                fix_prompt += "\n\nSOURCE TABLE CARDINALITIES (input sizes, not gold targets):\n"
                fix_prompt += "\n".join(counts_lines)
                fix_prompt += (
                    "\n- Use these to detect fan-out: if your output row count > largest plausible source slice, JOIN is duplicating rows."
                    "\n- If output << any source table that should feed into it: check for over-filtering or wrong JOIN type."
                    "\nROW COUNT AUDIT:\n"
                    "1. SELECT COUNT(*) FROM <model>; SELECT COUNT(DISTINCT <pk>) FROM <source>\n"
                    "2. If model > source distinct pk: fan-out — find the JOIN causing duplication\n"
                    "3. If model << source: check WHERE and JOIN types for over-filtering"
                )

            try:
                asyncio.run(_run_quick_fix_agent(fix_prompt, work_dir, model))
            except Exception as e:
                log(f"Quick-fix agent failed: {e}", "WARN")

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

        # NEW: post-success value verification agent (triggers always when eval-critical tables may exist)
        _result_db = _find_result_db(work_dir)
        if eval_critical_models and _result_db:
            verify_prompt = _build_value_verify_prompt(
                work_dir, instance_id, eval_critical_models, instruction,
                _extract_model_columns(work_dir)
            )
            try:
                asyncio.run(_run_value_verify_agent(verify_prompt, work_dir, model))
            except Exception as e:
                log(f"Value-verify agent failed: {e}", "WARN")
            # Re-run dbt to materialize any fixes
            subprocess.run(
                ["/home/agentuser/.local/bin/dbt", "run", "--select"] + [f"+{m}" for m in sorted(eval_critical_models)],
                cwd=str(work_dir), capture_output=True, text=True, timeout=180,
            )

        # Post-agent check: are all eval-critical tables in the result DB?
        if eval_critical_models:
            _result_db = _find_result_db(work_dir)
            if _result_db:
                try:
                    import duckdb as _ddb
                    _con = _ddb.connect(str(_result_db), read_only=True)
                    existing_tables = set(r[0] for r in _con.execute("SHOW TABLES").fetchall())
                    _con.close()
                    missing_eval_tables = eval_critical_models - existing_tables
                    if missing_eval_tables:
                        log(f"POST-EVAL CHECK: Missing eval-critical tables: {sorted(missing_eval_tables)}", "WARN")
                        # Build the list of similar-looking existing tables as hints
                        similar_hints = []
                        for missing in sorted(missing_eval_tables):
                            # Find tables that share any significant word with the missing name
                            missing_parts = set(missing.replace('__', '_').split('_'))
                            for existing in sorted(existing_tables):
                                existing_parts = set(existing.replace('__', '_').split('_'))
                                if len(missing_parts & existing_parts) >= 2:
                                    similar_hints.append(f"  '{existing}' may contain the data for '{missing}'")

                        name_fix_prompt = f"""Fix missing output tables in the dbt project at {work_dir}.

Task: {instruction}

PROBLEM: The following required table names do NOT exist in the result database:
{chr(10).join(f"  - {t}" for t in sorted(missing_eval_tables))}

CURRENT TABLES IN DATABASE:
{chr(10).join(f"  - {t}" for t in sorted(existing_tables))}

{("SIMILAR EXISTING TABLES (may have the right data under a wrong name):" + chr(10) + chr(10).join(similar_hints)) if similar_hints else ""}

STEPS TO FIX:
1. List files in models/ to find existing SQL files: ls models/*.sql models/**/*.sql
2. Find the model that computes the required data (look for similar logic/name)
3. Create a new .sql file with the EXACT required name:
   Example for missing 'zuora__account_overview':
   Create models/zuora__account_overview.sql:
     {{{{ config(materialized='table') }}}}
     SELECT * FROM {{{{ ref('your_existing_model_name') }}}}
   OR rename the existing file if no downstream models depend on it.
4. Run: dbt run --select {" ".join(sorted(missing_eval_tables))}
5. Verify: run SHOW TABLES and confirm the exact name appears.

RULES:
- Do NOT modify .yml files
- Use materialized='table' in config
- DuckDB SQL only
- The table name must be exactly: {", ".join(sorted(missing_eval_tables))}
{"- NEVER run dbt deps — it will wipe pre-installed packages!" if not (work_dir / "packages.yml").exists() else ""}"""

                        col_specs = []
                        model_columns = _extract_model_columns(work_dir)
                        for model_name in sorted(missing_eval_tables):
                            if model_name in model_columns:
                                col_specs.append(f"  {model_name}: {', '.join(model_columns[model_name])}")
                        if col_specs:
                            name_fix_prompt += "\n\nREQUIRED COLUMNS:\n" + "\n".join(col_specs)

                        try:
                            name_fix_ok = asyncio.run(_run_name_fix_agent(name_fix_prompt, work_dir, model))
                        except Exception as e:
                            log(f"Name-fix agent failed: {e}", "WARN")
                            name_fix_ok = False
                        if name_fix_ok:
                            # Run dbt one more time to materialize fixed models
                            subprocess.run(
                                ["/home/agentuser/.local/bin/dbt", "run", "--select"]
                                + list(sorted(missing_eval_tables)),
                                cwd=str(work_dir), capture_output=True, text=True, timeout=180,
                            )
                except Exception as e:
                    log(f"Post-eval table check failed: {e}", "WARN")

        # Row-count and value-fix agents removed — they leaked gold data
        # (gold row counts and sample values were passed directly to fix agents)

    # ── Flush DuckDB WAL before evaluation ──────────────────────────────────
    # The SDK's MCP server subprocess may still hold write connections.
    # Open a write connection briefly to force a WAL checkpoint, then close.
    _result_db = _find_result_db(work_dir)
    if _result_db:
        try:
            import duckdb as _ddb
            _flush_con = _ddb.connect(database=str(_result_db))
            _flush_con.execute("CHECKPOINT")
            _flush_con.close()
            log("Flushed DuckDB WAL via CHECKPOINT")
        except Exception as e:
            log(f"WAL flush failed (non-fatal): {e}", "WARN")
    # Also delete the MCP connection registration
    try:
        from gateway.store import delete_connection as _del_conn
        _del_conn(instance_id)
        log(f"Released MCP connection '{instance_id}' before evaluation")
    except Exception:
        pass
    time.sleep(2)  # Extra time for cleanup

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

    # Clean up connection to prevent cross-task leakage
    try:
        from gateway.store import delete_connection
        delete_connection(instance_id)
        log(f"Cleaned up connection '{instance_id}'")
    except Exception:
        pass

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
