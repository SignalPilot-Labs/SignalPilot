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
    import urllib.request
    import urllib.error

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


# ── Agent ────────────────────────────────────────────────────
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


def build_system_prompt(instruction: str, project_context: str, instance_id: str) -> str:
    return f"""You are a data scientist proficient in database, SQL and DBT Project.
You are working in {TEST_ENV / instance_id}, which contains a DuckDB-based dbt project.

## Task
{instruction}

## Database Access
You have access to SignalPilot MCP tools for database exploration and queries.
The DuckDB database is registered as connection '{instance_id}'.

Use these tools to explore the database:
- `mcp__signalpilot__list_tables` — list all tables
- `mcp__signalpilot__describe_table` — get column details
- `mcp__signalpilot__explore_table` — deep-dive with sample values
- `mcp__signalpilot__query_database` — run SQL queries (read-only)
- `mcp__signalpilot__schema_overview` — quick DB overview
- `mcp__signalpilot__find_join_path` — find join path between tables

You also have file tools (Read, Write, Glob, Grep) and Bash for running dbt commands.

## DBT Project Hints
1. Read the dbt project files. Your task is to write SQL queries for data transformation.
2. Use SignalPilot tools to explore the DuckDB database (schema, sample data, relationships).
3. Review YAML files to understand task requirements and identify incomplete model SQLs.
4. The project is unfinished — identify models defined in .yml but missing .sql files.
5. Do NOT modify .yml files — write correct SQL based on existing YAML definitions.
6. After writing all required SQL, run `dbt deps && dbt run` via Bash.
7. Verify new data models using SignalPilot query_database.
8. Use DuckDB-compatible SQL syntax (not PostgreSQL, not MySQL).
9. Use dbt ref() and source() macros correctly.

## Current Project Files
{project_context}

## Instructions
1. Explore the database schema using SignalPilot tools
2. Identify which .yml files don't have corresponding .sql files
3. Read existing SQL files to understand naming conventions
4. Write each missing .sql file
5. Run `dbt deps && dbt run` via Bash to validate
6. If dbt run fails, read the error, fix the SQL, and re-run
7. Verify the models using SignalPilot query_database"""


async def run_agent(instance_id: str, instruction: str, project_dir: Path,
                    model: str, max_turns: int, budget: float,
                    use_mcp: bool) -> dict:
    """Run the Claude agent locally."""
    from claude_agent_sdk import (
        AssistantMessage, ClaudeAgentOptions, ResultMessage,
        TextBlock, ToolResultBlock, ToolUseBlock, query,
    )

    project_context = collect_project_context(project_dir)
    system_prompt = build_system_prompt(instruction, project_context, instance_id)
    user_prompt = (
        f"Complete this dbt project. The task is: {instruction}\n\n"
        f"Identify which models have .yml definitions but no .sql files, and write the SQL for each one. "
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
        # No tool restrictions — real-world test
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

    deps = subprocess.run(
        [sys.executable, "-m", "dbt", "deps"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=120,
    )
    for line in (deps.stdout + deps.stderr).strip().split("\n"):
        if line.strip():
            log(f"  dbt deps: {line.strip()}")

    result = subprocess.run(
        [sys.executable, "-m", "dbt", "run"],
        cwd=str(project_dir), capture_output=True, text=True, timeout=120,
    )
    output = result.stdout + "\n" + result.stderr
    for line in output.strip().split("\n"):
        if line.strip():
            log(f"  dbt run: {line.strip()}")

    log(f"dbt run exit code: {result.returncode}")
    return result.returncode == 0, output


# ── Evaluate ─────────────────────────────────────────────────
def evaluate(project_dir: Path, instance_id: str) -> tuple[bool, str]:
    """Evaluate result against gold standard."""
    import duckdb

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

        if gold_sub.shape != pred_sub.shape:
            details.append(f"  {tab}: FAIL - shape mismatch gold={gold_sub.shape} pred={pred_sub.shape}")
            log(f"  FAIL - shape mismatch")
            all_match = False
            continue

        if ignore_orders[i]:
            gold_sub = gold_sub.sort_values(by=list(gold_sub.columns)).reset_index(drop=True)
            pred_sub = pred_sub.sort_values(by=list(pred_sub.columns)).reset_index(drop=True)

        try:
            match = True
            mismatch_col = None
            for col in gold_sub.columns:
                g = gold_sub[col]
                p = pred_sub[col]
                if g.dtype in ("float64", "float32", "int64", "int32"):
                    if not all(abs(a - b) < 0.01 for a, b in zip(g.fillna(0), p.fillna(0))):
                        match = False
                        mismatch_col = col
                        break
                else:
                    if not all(str(a).strip().lower() == str(b).strip().lower() for a, b in zip(g.fillna(""), p.fillna(""))):
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
    parser.add_argument("--max-turns", type=int, default=30)
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
