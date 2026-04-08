"""
Local Spider2-DBT benchmark runner — no Docker required.

Runs the Claude Agent SDK directly on the host in benchmark/test-env/<instance_id>.
Each run gets a clean copy of the task project + skills. The test-env directory
is cleaned before each run.

Usage:
    python -m benchmark.run_dbt_local chinook001
    python -m benchmark.run_dbt_local chinook001 --model claude-sonnet-4-6
    python -m benchmark.run_dbt_local chinook001 --skip-agent   # just eval
"""

from __future__ import annotations

import io
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import argparse
import asyncio
import json
import os
import shutil
import stat
import subprocess
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# ── Paths (override via env or edit here) ────────────────────
SPIDER2_DBT_DIR = Path(os.environ.get(
    "SPIDER2_DBT_DIR",
    "C:/Users/kiwi0/Desktop/what/spider2-repo/spider2-dbt",
))
EXAMPLES_DIR = SPIDER2_DBT_DIR / "examples"
GOLD_DIR = SPIDER2_DBT_DIR / "evaluation_suite" / "gold"
EVAL_JSONL = GOLD_DIR / "spider2_eval.jsonl"
TEST_ENV = BENCHMARK_DIR / "test-env"
SKILLS_SRC = BENCHMARK_DIR / "skills"
GATEWAY_SRC = PROJECT_ROOT / "signalpilot" / "gateway"
GATEWAY_URL = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
DBT_BIN = shutil.which("dbt") or str(Path.home() / ".local" / "bin" / "dbt")


# ── Helpers ──────────────────────────────────────────────────
def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def _force_rmtree(path: Path):
    def on_error(func, fpath, exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
    shutil.rmtree(path, onerror=on_error)


def load_task(instance_id: str) -> dict:
    with open(EXAMPLES_DIR / "spider2-dbt.jsonl") as f:
        for line in f:
            task = json.loads(line.strip())
            if task["instance_id"] == instance_id:
                return task
    raise ValueError(f"Task {instance_id} not found")


def load_eval_config(instance_id: str) -> dict | None:
    if not EVAL_JSONL.exists():
        return None
    with open(EVAL_JSONL) as f:
        for line in f:
            entry = json.loads(line.strip())
            if entry["instance_id"] == instance_id:
                return entry
    return None


# ── Setup ────────────────────────────────────────────────────
def prepare_test_env(instance_id: str) -> Path:
    """Create a clean test environment with task project + skills."""
    project_dir = TEST_ENV / instance_id

    # Clean up previous run
    if project_dir.exists():
        log(f"Cleaning previous test-env/{instance_id}")
        _force_rmtree(project_dir)

    # Copy task project
    src = EXAMPLES_DIR / instance_id
    if not src.exists():
        raise FileNotFoundError(f"Task example not found: {src}")
    shutil.copytree(src, project_dir)

    # Copy skills into .claude/skills/
    skills_dst = project_dir / ".claude" / "skills"
    if SKILLS_SRC.exists():
        shutil.copytree(SKILLS_SRC, skills_dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.json", "__pycache__"))
        skill_count = len(list(skills_dst.rglob("SKILL.md")))
        log(f"Copied {skill_count} skills to .claude/skills/")

    return project_dir


def setup_signalpilot(instance_id: str, project_dir: Path):
    """Clear all SignalPilot connections, register only this task's DuckDB."""
    log(f"Setting up SignalPilot ({GATEWAY_URL})")

    # Check if gateway is running
    try:
        req = urllib.request.Request(f"{GATEWAY_URL}/api/connections")
        with urllib.request.urlopen(req, timeout=3) as resp:
            connections = json.loads(resp.read())
    except Exception:
        log("SignalPilot gateway not reachable — skipping MCP setup", "WARN")
        log(f"Start it with: cd signalpilot && docker compose -f docker/docker-compose.dev.yml up -d")
        return False

    # Delete all existing connections
    for conn in connections:
        name = conn.get("name", "")
        try:
            del_req = urllib.request.Request(f"{GATEWAY_URL}/api/connections/{name}", method="DELETE")
            urllib.request.urlopen(del_req, timeout=5)
            log(f"  Removed connection: {name}")
        except Exception:
            pass

    # Register this task's DuckDB
    duckdb_files = list(project_dir.glob("*.duckdb"))
    if not duckdb_files:
        log("No DuckDB file found in project", "WARN")
        return False

    db_path = str(duckdb_files[0].resolve())
    payload = json.dumps({
        "name": instance_id,
        "db_type": "duckdb",
        "database": db_path,
        "description": f"Spider2-DBT benchmark: {instance_id}",
    }).encode()

    try:
        req = urllib.request.Request(
            f"{GATEWAY_URL}/api/connections",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log(f"  Registered: {instance_id} -> {db_path}")
        return True
    except Exception as e:
        log(f"  Registration failed: {e}", "WARN")
        return False


def fetch_schema_ddl(instance_id: str, project_dir: Path) -> str:
    """Generate compact DDL locally from the task's DuckDB file."""
    import duckdb as _duckdb

    DDL_SIZE_LIMIT = 15000
    duckdb_files = list(project_dir.glob("*.duckdb"))
    if not duckdb_files:
        log("No DuckDB file found for DDL generation", "WARN")
        return ""

    try:
        con = _duckdb.connect(str(duckdb_files[0]), read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        parts = []
        for table in sorted(tables):
            cols = con.execute(f"PRAGMA table_info('{table}')").fetchall()
            count = con.execute(f"SELECT COUNT(*) FROM \"{table}\"").fetchone()[0]
            col_defs = ", ".join(f"{c[1]} {c[2]}" for c in cols)
            parts.append(f"-- {table} ({count} rows)\nCREATE TABLE {table} ({col_defs});")
        con.close()
        ddl = "\n".join(parts)
        if len(ddl) > DDL_SIZE_LIMIT:
            log(f"Schema DDL too large ({len(ddl)} chars) — skipping injection", "WARN")
            return ""
        log(f"Generated DDL locally: {len(tables)} tables, {len(ddl)} chars")
        return ddl
    except Exception as e:
        log(f"fetch_schema_ddl failed: {e}", "WARN")
        return ""


# ── Agent ────────────────────────────────────────────────────
ALLOWED_TOOLS = [
    # File operations
    "Read", "Write", "Edit", "Glob", "Grep", "Bash",
    # MCP — schema discovery
    "mcp__signalpilot__query_database",
    "mcp__signalpilot__describe_table",
    "mcp__signalpilot__explore_table",
    # MCP — useful but lower priority
    "mcp__signalpilot__find_join_path",
    "mcp__signalpilot__get_relationships",
]


def collect_project_context(project_dir: Path) -> str:
    parts = []
    for fpath in sorted(project_dir.rglob("*")):
        if fpath.is_dir():
            continue
        if fpath.suffix in (".duckdb", ".zip", ".pyc", ".lock"):
            continue
        if any(skip in str(fpath) for skip in ("dbt_packages", "target", "logs", ".claude", "__pycache__")):
            continue
        rel = fpath.relative_to(project_dir)
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        parts.append(f"### {rel}\n```\n{content}\n```")
    return "\n\n".join(parts)


def build_system_prompt(instruction: str, project_context: str, instance_id: str, schema_ddl: str, dbt_bin: str) -> str:
    work_dir = TEST_ENV / instance_id

    if schema_ddl:
        schema_section = f"""## Source Database Schema (DDL)
Connection: '{instance_id}'
{schema_ddl}"""
    else:
        schema_section = f"""## Source Database
Connection: '{instance_id}' — use mcp__signalpilot__query_database to explore schema."""

    return f"""You are a dbt + DuckDB data engineer working in {work_dir}.

## Task
{instruction}

{schema_section}

## Project Files
{project_context}

## Important — all project files are already included above
Do NOT re-read or re-explore files that are shown in "Project Files" above.
Go directly to Step 0. You already have all the information you need.

## Workflow — follow exactly in order

### Step 0 — Run dbt immediately to detect existing errors
Run: `{dbt_bin} deps && {dbt_bin} run`
Do NOT write any SQL yet. Read the output carefully:
- If it exits 0: note which models already work — do not break them
- If it fails: record the exact error messages — these tell you what is missing or broken
This diagnostic run is mandatory. It reveals the real state of the project before you touch anything.

### Step 1 — Map ALL missing models (two phases)

**Phase A — YAML scan:**
For every `.yml` file under `models/`, find each model in a `models:` block.
Check whether a `.sql` file with that exact name exists.
Build list of (model_name, yaml_path) pairs for all missing SQL files.
Also scan existing `.sql` files for truncation (trailing comma, unclosed CTE) and fix before writing new ones.

**Phase B — Instruction-driven scan:**
Re-read the Task instruction above. Extract every table or model name mentioned as a
deliverable or output (e.g., "create a model called X", "build a table for each Y category").
For each name: if no .sql file exists, add it to your build list — even if no .yml entry exists.
Use the task description and Source Database Schema as your spec for that model's columns and logic.

Do not proceed to Step 2 until your list covers BOTH phases.

### Step 2 — Understand dependencies
For each missing model, read its YAML `refs:` list. Determine build order:
write upstream models before downstream ones.

### Step 3 — Write SQL
For each missing model (in dependency order):
- Column aliases must EXACTLY match the YAML `columns:` names — case-sensitive
- Use `{{{{ ref('model_name') }}}}` for other models, `{{{{ source('schema', 'table') }}}}` for raw tables
- Use DuckDB syntax (no DATEADD, no ::date on non-ISO strings, INTERVAL '1' DAY not +1)
- Add `{{{{ config(materialized='table') }}}}` at the top

### Step 4 — Run and fix
Run: `{dbt_bin} deps && {dbt_bin} run`
If errors: read the ERROR lines, fix the specific model, re-run.
Use `dbt run --select model_name` to test a single model when debugging.

### Step 5 — Verify (REQUIRED before stopping)
For each model you created, run a SQL query via `mcp__signalpilot__query_database`
to confirm it produced rows: `SELECT COUNT(*) FROM model_name`
If a model has 0 rows and it should have data, something is wrong — debug it.

Also check for too-many-rows:
- A summary model (one row per driver, year, category) should return COUNT(*) equal to
  COUNT(DISTINCT group_key). If it returns more, your JOIN is fanning out or GROUP BY is missing a column.
- A detail model should return <= source row count unless the JOIN intentionally expands rows.
- If counts are unexpectedly high: add a missing WHERE clause, switch LEFT JOIN to INNER JOIN,
  or pre-aggregate the right side of a JOIN before joining.

### STOP only when: dbt run exits 0 AND all your new models have row counts > 0.

## Rules
- Do NOT modify `.yml` files unless fixing a missing `schema:` in a source definition
- Do NOT use PostgreSQL/MySQL syntax
- Do NOT guess column names — use the YAML `columns:` list as the source of truth

## Critical Warning — do NOT create passthrough models for raw tables

If dbt reports "source not found" or staging models use {{{{ source('schema', 'table') }}}},
DO NOT create new .sql files named after the raw tables (e.g. circuits.sql, results.sql).
Materializing a model with the same name as a raw table DESTROYS the source data by replacing
it with a view. The database cannot recover from this within the current run.

Instead: check the source definition YAML and ensure the `schema:` in the source block
matches where raw tables live in DuckDB (usually `main`). If the schema is missing, add
`schema: main` to the source definition in the YAML. This is the ONE case where editing
a .yml file is acceptable.

## Fixing ref() errors — missing model files

If dbt reports `Compilation Error: ... not found` for a ref() call and the referenced .sql
file does not exist, first check whether the name is a raw table in the DuckDB source:

    SELECT table_name FROM information_schema.tables WHERE table_name = 'name'

**Preferred fix — ephemeral stub:**
If the table exists in DuckDB, create models/<name>.sql:

    {{{{ config(materialized='ephemeral') }}}}
    select * from main.<name>

Ephemeral models are inlined as CTEs. They create NO database object and will NOT shadow
or overwrite source data. This is safe. Use this when existing staging models you did not
write use ref('name') and you do not want to rewrite those models.

**Fallback fix — rewrite the ref() call:**
If ephemeral inlining causes nested CTE issues, replace {{{{ ref('name') }}}} with main.name
directly in the calling model.

If existing staging models use {{{{ ref('raw_table') }}}} to reference raw tables instead of
{{{{ source('source_name', 'raw_table') }}}}, the ephemeral stub is the correct fix — do not
add a schema: main override to the YAML unless the error is specifically "source not found"
(a different error from "node not found")."""


async def run_agent(instance_id: str, instruction: str, project_dir: Path,
                    model: str, max_turns: int, budget: float,
                    use_mcp: bool) -> dict:
    """Run the Claude agent locally."""
    from claude_agent_sdk import (
        AssistantMessage, ClaudeAgentOptions, ResultMessage,
        TextBlock, ToolResultBlock, ToolUseBlock, query,
    )

    project_context = collect_project_context(project_dir)
    schema_ddl = fetch_schema_ddl(instance_id, project_dir)
    system_prompt = build_system_prompt(instruction, project_context, instance_id, schema_ddl, dbt_bin=DBT_BIN)
    user_prompt = (
        f"Complete this dbt project. The task is: {instruction}\n\n"
        f"Identify ALL models that need to be created: (1) models in .yml files with no .sql, "
        f"(2) any model or table named in the task instruction that has no .sql file yet. "
        f"Write the SQL for each one. "
        f"Then run `dbt deps && dbt run` to validate."
    )

    log(f"System prompt: {len(system_prompt)} chars")
    log(f"Project context: {len(project_context)} chars")

    # MCP config
    mcp_config = None
    if use_mcp and GATEWAY_SRC.exists():
        mcp_config = {
            "signalpilot": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "gateway.mcp_server"],
                "cwd": str(GATEWAY_SRC),
                "env": {"SP_GATEWAY_URL": GATEWAY_URL},
            }
        }
        log(f"MCP configured: signalpilot at {GATEWAY_SRC}")

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        max_turns=max_turns,
        max_budget_usd=budget,
        permission_mode="bypassPermissions",
        cwd=str(project_dir),
        allowed_tools=ALLOWED_TOOLS,
        **({"mcp_servers": mcp_config} if mcp_config else {}),
    )

    messages = []
    tool_calls = []
    turn_count = 0
    start_time = time.monotonic()

    log(f"Agent starting: model={model}, max_turns={max_turns}, budget=${budget}")

    try:
        async for message in query(prompt=user_prompt, options=options):
            elapsed = time.monotonic() - start_time

            if isinstance(message, AssistantMessage):
                turn_count += 1
                log(f"--- Turn {turn_count} ({elapsed:.1f}s) ---")
                if turn_count >= max_turns:
                    log(f"Max turns ({max_turns}) reached — stopping agent early", "WARN")
                    break
                for block in message.content:
                    if isinstance(block, TextBlock):
                        for line in block.text.split("\n"):
                            log(f"  AGENT: {line}")
                        messages.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_input = json.dumps(block.input, ensure_ascii=False)
                        log(f"  TOOL: {block.name} -> {tool_input[:200]}")
                        tool_calls.append({"name": block.name, "turn": turn_count})
                    elif isinstance(block, ToolResultBlock):
                        result_str = str(getattr(block, "content", block))
                        log(f"  RESULT: {result_str[:300]}")

            elif isinstance(message, ResultMessage):
                log(f"Agent finished: {turn_count} turns, {elapsed:.1f}s")

    except Exception as e:
        log(f"Agent error: {e}", "ERROR")
        traceback.print_exc()
        return {"error": str(e), "messages": messages, "tool_calls": tool_calls}

    elapsed = time.monotonic() - start_time
    log(f"Agent complete: turns={turn_count}, tools={len(tool_calls)}, elapsed={elapsed:.1f}s")

    return {"messages": messages, "tool_calls": tool_calls, "elapsed": elapsed, "turns": turn_count}


# ── dbt run ──────────────────────────────────────────────────
def run_dbt(project_dir: Path) -> tuple[bool, str]:
    """Run dbt deps + dbt run as final validation."""
    log("Running dbt deps + dbt run (final validation)...")

    if not Path(DBT_BIN).exists():
        log(f"dbt binary not found at {DBT_BIN}", "WARN")
        return False, f"dbt binary not found at {DBT_BIN}"

    deps = subprocess.run(
        [DBT_BIN, "deps"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=120,
    )
    for line in (deps.stdout + deps.stderr).strip().split("\n"):
        if line.strip():
            log(f"  dbt deps: {line.strip()}")

    result = subprocess.run(
        [DBT_BIN, "run"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=120,
    )
    output = result.stdout + "\n" + result.stderr
    for line in output.strip().split("\n"):
        if line.strip():
            log(f"  dbt run: {line.strip()}")

    log(f"dbt run exit code: {result.returncode}")

    # Flush DuckDB WAL so subsequent reads (eval) see all materialized data
    try:
        import duckdb as _duckdb
        for db_file in project_dir.glob("*.duckdb"):
            con = _duckdb.connect(str(db_file))
            con.execute("CHECKPOINT")
            con.close()
            log(f"DuckDB CHECKPOINT: {db_file.name}")
    except Exception as e:
        log(f"DuckDB CHECKPOINT failed (non-fatal): {e}", "WARN")

    return result.returncode == 0, output


# ── Evaluate ─────────────────────────────────────────────────
def evaluate(project_dir: Path, instance_id: str) -> tuple[bool, str]:
    """Evaluate result against gold standard."""
    import duckdb
    import pandas as pd

    eval_config = load_eval_config(instance_id)
    if not eval_config:
        return False, "No evaluation config found"

    eval_params = eval_config["evaluation"]["parameters"]
    gold_db_path = str(GOLD_DIR / instance_id / eval_params["gold"])
    result_db_path = str(project_dir / eval_params["gold"])

    condition_tabs = eval_params.get("condition_tabs")
    condition_cols = eval_params.get("condition_cols")
    ignore_orders = eval_params.get("ignore_orders")

    log(f"Gold DB: {gold_db_path}")
    log(f"Result DB: {result_db_path}")

    if not Path(result_db_path).exists():
        return False, f"Result DB not found: {result_db_path}"
    if not Path(gold_db_path).exists():
        return False, f"Gold DB not found: {gold_db_path}\n  Run: python -m benchmark.setup_dbt --build-gold {instance_id}"

    def get_tables(db_path):
        con = duckdb.connect(database=db_path, read_only=True)
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        con.close()
        return tables

    def get_table(db_path, table_name):
        con = duckdb.connect(database=db_path, read_only=True)
        df = con.execute(f"SELECT * FROM {table_name}").fetchdf()
        con.close()
        return df

    result_tables = get_tables(result_db_path)
    gold_tables = get_tables(gold_db_path)
    log(f"Gold tables: {gold_tables}")
    log(f"Result tables: {result_tables}")

    if condition_tabs is None:
        condition_tabs = gold_tables
    if ignore_orders is None:
        ignore_orders = [False] * len(condition_tabs)
    if condition_cols is None:
        condition_cols = [[]] * len(condition_tabs)

    all_match = True
    details = []

    for i, tab in enumerate(condition_tabs):
        log(f"Checking table: {tab}")

        if tab not in result_tables:
            details.append(f"  {tab}: FAIL - not in result DB")
            log(f"  FAIL - '{tab}' not in result (have: {result_tables})")
            all_match = False
            continue

        try:
            gold_df = get_table(gold_db_path, tab)
            pred_df = get_table(result_db_path, tab)
        except Exception as e:
            details.append(f"  {tab}: ERROR - {e}")
            log(f"  ERROR: {e}")
            all_match = False
            continue

        log(f"  Gold: {gold_df.shape}, Result: {pred_df.shape}")

        cols = condition_cols[i] if condition_cols[i] else list(range(len(gold_df.columns)))
        try:
            gold_sub = gold_df.iloc[:, cols]
            pred_sub = pred_df.iloc[:, cols]
        except IndexError as e:
            details.append(f"  {tab}: FAIL - column index error: {e}")
            all_match = False
            continue

        # Align column names: cols are selected by index, so positional match is correct
        pred_sub.columns = gold_sub.columns

        if gold_sub.shape != pred_sub.shape:
            details.append(f"  {tab}: FAIL - shape mismatch gold={gold_sub.shape} pred={pred_sub.shape}")
            log(f"  FAIL - shape mismatch")
            all_match = False
            continue

        if ignore_orders[i]:
            try:
                gold_sub = gold_sub.sort_values(by=list(gold_sub.columns)).reset_index(drop=True)
                pred_sub = pred_sub.sort_values(by=list(pred_sub.columns)).reset_index(drop=True)
            except (TypeError, ValueError):
                # Mixed/nullable types can't sort directly — sort by string representation
                sort_cols = list(gold_sub.columns)
                gold_order = gold_sub.apply(lambda c: c.astype(str)).sort_values(by=sort_cols).index
                pred_order = pred_sub.apply(lambda c: c.astype(str)).sort_values(by=sort_cols).index
                gold_sub = gold_sub.loc[gold_order].reset_index(drop=True)
                pred_sub = pred_sub.loc[pred_order].reset_index(drop=True)

        try:
            match = True
            mismatch_col = None
            for col in gold_sub.columns:
                g = gold_sub[col]
                p = pred_sub[col]
                is_numeric = pd.api.types.is_numeric_dtype(g) or pd.api.types.is_numeric_dtype(p)
                if is_numeric:
                    try:
                        gn = pd.to_numeric(g, errors="coerce").fillna(0)
                        pn = pd.to_numeric(p, errors="coerce").fillna(0)
                        if not all(abs(a - b) < 0.01 for a, b in zip(gn, pn)):
                            match = False
                            mismatch_col = col
                            break
                    except Exception:
                        # Fall through to string comparison
                        gs = g.astype(str).replace({"<NA>": "", "nan": "", "None": ""})
                        ps = p.astype(str).replace({"<NA>": "", "nan": "", "None": ""})
                        if not all(str(a).strip().lower() == str(b).strip().lower() for a, b in zip(gs, ps)):
                            match = False
                            mismatch_col = col
                            break
                else:
                    gs = g.astype(str).replace({"<NA>": "", "nan": "", "None": ""})
                    ps = p.astype(str).replace({"<NA>": "", "nan": "", "None": ""})
                    if not all(str(a).strip().lower() == str(b).strip().lower() for a, b in zip(gs, ps)):
                        match = False
                        mismatch_col = col
                        break

            if match:
                details.append(f"  {tab}: PASS ({gold_sub.shape[0]} rows, {len(cols)} cols)")
                log(f"  PASS - {gold_sub.shape[0]} rows, {len(cols)} cols")
            else:
                details.append(f"  {tab}: FAIL - values mismatch (column: {mismatch_col})")
                log(f"  FAIL - mismatch in column '{mismatch_col}'")
                all_match = False
        except Exception as e:
            details.append(f"  {tab}: FAIL - comparison error: {e}")
            all_match = False

    return all_match, "\n".join(details)


# ── Main ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Run a Spider2-DBT benchmark task locally (no Docker)")
    parser.add_argument("instance_id", default="chinook001", nargs="?")
    parser.add_argument("--model", default="claude-opus-4-6")
    parser.add_argument("--max-turns", type=int, default=45)
    parser.add_argument("--budget", type=float, default=5.0)
    parser.add_argument("--skip-agent", action="store_true", help="Skip agent, just eval existing results")
    parser.add_argument("--no-mcp", action="store_true", help="Disable SignalPilot MCP")
    parser.add_argument("--adopt-gold", action="store_true", help="After run, adopt result as gold DB")
    args = parser.parse_args()

    instance_id = args.instance_id
    print(f"{'=' * 60}")
    print(f"Spider2-DBT Local Benchmark - {instance_id}")
    print(f"{'=' * 60}")

    # Load task
    task = load_task(instance_id)
    log(f"Task: {task['instruction']}")

    # Prepare test environment
    if args.skip_agent:
        project_dir = TEST_ENV / instance_id
        if not project_dir.exists():
            print(f"No previous results at {project_dir}")
            sys.exit(1)
    else:
        project_dir = prepare_test_env(instance_id)

    log(f"Work dir: {project_dir}")

    if not args.skip_agent:
        # Setup SignalPilot
        use_mcp = not args.no_mcp
        if use_mcp:
            use_mcp = setup_signalpilot(instance_id, project_dir)

        # Run agent
        result = asyncio.run(run_agent(
            instance_id=instance_id,
            instruction=task["instruction"],
            project_dir=project_dir,
            model=args.model,
            max_turns=args.max_turns,
            budget=args.budget,
            use_mcp=use_mcp,
        ))

        if "error" in result:
            log(f"Agent failed: {result['error']}", "ERROR")

        # Final dbt validation
        dbt_ok, dbt_output = run_dbt(project_dir)

        # Log DuckDB state
        try:
            import duckdb
            for db in project_dir.glob("*.duckdb"):
                con = duckdb.connect(str(db), read_only=True)
                tables = con.execute("SHOW TABLES").fetchall()
                log(f"{db.name}: {len(tables)} tables")
                for t in tables:
                    count = con.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
                    log(f"  {t[0]}: {count} rows")
                con.close()
        except Exception as e:
            log(f"DuckDB inspection error: {e}", "WARN")

        # Save result
        result_data = {
            "success": dbt_ok,
            "agent_elapsed": result.get("elapsed", 0),
            "agent_turns": result.get("turns", 0),
            "tool_calls": result.get("tool_calls", []),
        }
        (project_dir / "agent_result.json").write_text(json.dumps(result_data, indent=2))

    # Evaluate
    print(f"\n{'=' * 60}")
    print(f"Evaluating against gold standard...")
    print(f"{'=' * 60}")

    try:
        passed, details = evaluate(project_dir, instance_id)
        print(details)

        # Adopt as gold if requested and passed
        if args.adopt_gold and passed:
            from .setup_dbt import adopt_result_as_gold
            adopt_result_as_gold(instance_id, SPIDER2_DBT_DIR.parent, project_dir)

        print(f"\n{'=' * 60}")
        print(f"RESULT: {'PASS' if passed else 'FAIL'}")
        print(f"{'=' * 60}")
    except Exception as e:
        print(f"\n  Evaluation error: {e}")
        traceback.print_exc()
        print(f"\n{'=' * 60}")
        print(f"RESULT: ERROR")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
