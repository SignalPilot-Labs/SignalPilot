"""ADE-bench runner — runs ADE-bench tasks through our Spider2 infrastructure.

Uses the same Claude Agent SDK + MCP + SignalPilot plugin stack as Spider2-DBT,
but with ADE-bench task definitions, project setup, and dbt-test-based evaluation.

Usage:
    python -m benchmark.ade.runner airbnb001
    python -m benchmark.ade.runner airbnb001 --model claude-sonnet-4-6
    python -m benchmark.ade.runner --list   # list all ready tasks
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

from ..agent.sdk_runner import run_sdk_agent
from ..core.audit import save_single_task_run
from ..core.logging import log, log_separator
from ..core.mcp import delete_local_connection, register_local_connection
from ..core.paths import PROMPTS_DIR, ensure_local_bin_on_path
from .evaluator import evaluate_ade_task
from .tasks import list_ready_tasks, load_task
from .workdir import prepare_ade_workdir

ensure_local_bin_on_path()

DBT_BIN = shutil.which("dbt") or "/home/agentuser/.local/bin/dbt"

# Reuse the same system prompt template as Spider2-DBT
_SYSTEM_PROMPT_TEMPLATE: str = (PROMPTS_DIR / "dbt_local_system.md").read_text()

# ADE-bench work directory (separate from Spider2)
_ADE_WORK_BASE = Path(os.environ.get("ADE_WORK_DIR", str(
    Path(__file__).resolve().parent.parent / "_ade_workdir"
)))


def _write_claude_md(work_dir: Path) -> None:
    """Copy dbt_local_system.md as CLAUDE.md."""
    shutil.copy2(PROMPTS_DIR / "dbt_local_system.md", work_dir / "CLAUDE.md")
    log("Wrote CLAUDE.md (from dbt_local_system.md)")


def _find_duckdb(work_dir: Path) -> Path | None:
    """Find the DuckDB database file in the work directory."""
    dbs = list(work_dir.glob("*.duckdb"))
    return dbs[0] if dbs else None


async def _run_agent(
    task_id: str,
    prompt: str,
    work_dir: Path,
    model: str,
    max_turns: int,
    continue_conversation: bool = False,
) -> dict:
    """Run the Claude Agent SDK (async portion only)."""
    agent_prompt = prompt
    system_prompt = (
        _SYSTEM_PROMPT_TEMPLATE
        .replace("${work_dir}", str(work_dir))
        .replace("${instance_id}", task_id)
        .replace("${dbt_bin}", DBT_BIN)
    )

    print("--- SYSTEM PROMPT START ---", flush=True)
    print(system_prompt, flush=True)
    print("--- SYSTEM PROMPT END ---", flush=True)
    print("--- USER PROMPT START ---", flush=True)
    print(agent_prompt, flush=True)
    print("--- USER PROMPT END ---", flush=True)

    result = await run_sdk_agent(
        agent_prompt,
        work_dir,
        model,
        max_turns,
        timeout=900,
        label="ade-agent",
        system_prompt=system_prompt,
        continue_conversation=continue_conversation,
    )

    # Save transcript
    (work_dir / "agent_output.json").write_text(json.dumps({
        "transcript": result["transcript"],
        "tool_calls": result["tool_calls"],
        "messages": result["messages"],
        "turns": result["turns"],
    }))

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ADE-bench tasks")
    parser.add_argument("task_id", nargs="?", help="Task ID (e.g., airbnb001)")
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--skip-agent", action="store_true")
    parser.add_argument("--list", action="store_true", help="List all ready tasks")
    args = parser.parse_args()

    if args.list:
        tasks = list_ready_tasks()
        print(f"{len(tasks)} ready tasks:")
        for t in tasks:
            print(f"  {t}")
        return

    if not args.task_id:
        parser.error("task_id required (or use --list)")

    task_id: str = args.task_id
    model: str = args.model
    max_turns: int = args.max_turns
    _main_start = time.monotonic()

    # ── Load task ─────────────────────────────────────────────────────────────
    log_separator(f"ADE-bench Task: {task_id}")
    task = load_task(task_id)
    prompt = task["prompt"]
    log(f"Model:     {model}")
    log(f"Max turns: {max_turns}")
    log(f"Prompt: {prompt[:200]}")
    log(f"Difficulty: {task['difficulty']}")
    log(f"Solution seeds: {task['solution_seeds']}")

    # ── Step 1: Prepare workdir (sync) ────────────────────────────────────────
    log_separator("Step 1: Prepare workdir")
    _ADE_WORK_BASE.mkdir(parents=True, exist_ok=True)
    work_dir = prepare_ade_workdir(task, _ADE_WORK_BASE)
    log(f"Workdir: {work_dir}")

    agent_result: dict = {
        "success": False, "messages": [], "tool_calls": [], "turns": 0,
        "elapsed": 0.0, "cost_usd": None, "usage": None, "started_at": "",
    }

    if not args.skip_agent:
        # ── Step 2: Write CLAUDE.md (sync) ────────────────────────────────────
        log_separator("Step 2: Write CLAUDE.md")
        _write_claude_md(work_dir)

        # ── Step 3: Register DuckDB connection ───────────────────────────────
        # Register ONCE: the gateway's async engine is a module-level singleton
        # whose pooled asyncpg connection binds to the first event loop. Calling
        # asyncio.run() more than once reuses that connection on a closed loop,
        # raising "another operation is in progress". So register once, then poll
        # the verify GET (plain HTTP, no asyncio.run) for visibility.
        log_separator("Step 3: Register DuckDB connection")
        db_path = _find_duckdb(work_dir)
        if db_path:
            import time as _time
            import httpx as _httpx
            delete_local_connection(task_id)
            register_local_connection(task_id, str(db_path))
            _gw = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
            _org = os.environ.get("SP_ORG_ID", "local")
            visible = False
            for poll in range(5):
                try:
                    resp = _httpx.get(
                        f"{_gw}/api/connections",
                        timeout=5,
                        headers={"x-org-id": _org},
                    )
                    conns = resp.json() if resp.status_code == 200 else []
                    conn_names = [c.get("name", "") for c in conns] if isinstance(conns, list) else []
                    if task_id in conn_names:
                        visible = True
                        log(f"VERIFIED: connection '{task_id}' visible (poll {poll + 1})")
                        break
                except Exception as e:
                    log(f"Connection verify error (poll {poll + 1}): {e}", "WARN")
                _time.sleep(1.5)
            if not visible:
                log(f"WARNING: connection '{task_id}' NOT visible after registration", "WARN")
        else:
            log("No DuckDB file found!", "WARN")

        # ── Step 4: Run agent (async) ─────────────────────────────────────────
        log_separator("Step 4: Run Claude agent")
        t_agent = time.monotonic()
        try:
            agent_result = asyncio.run(_run_agent(
                task_id, prompt, work_dir, model, max_turns,
            ))
        except Exception as e:
            log(f"Agent error: {e}", "ERROR")
        elapsed_agent = time.monotonic() - t_agent
        log(f"Agent finished in {elapsed_agent:.1f}s")

    # ── Flush DuckDB WAL ──────────────────────────────────────────────────────
    db_path = _find_duckdb(work_dir)
    if db_path and db_path.exists():
        try:
            import duckdb
            con = duckdb.connect(str(db_path))
            con.execute("CHECKPOINT")
            con.close()
            log("Flushed DuckDB WAL")
        except Exception as e:
            log(f"WAL flush failed: {e}", "WARN")

    # Release MCP connection
    delete_local_connection(task_id)
    time.sleep(2)

    # ── Step 5: Evaluate ──────────────────────────────────────────────────────
    log_separator("Step 5: Evaluate (dbt seed + dbt test)")
    passed = False
    details = "evaluation not run"
    try:
        passed, details = evaluate_ade_task(work_dir, task)
    except Exception as e:
        log(f"Evaluation error: {e}", "ERROR")
        details = f"evaluation error: {e}"

    total_elapsed = time.monotonic() - _main_start
    log(f"Total elapsed: {total_elapsed:.1f}s")
    log_separator(f"RESULT: {'PASS' if passed else 'FAIL'} — {details}")

    # ── Step 6: Post-grade review (failures only) ────────────────────────────
    if not passed and not args.skip_agent:
        log_separator("Step 6: Post-grade review")
        try:
            from .post_grade import _inject_gold
            _inject_gold(work_dir, task)
            review_prompt = (PROMPTS_DIR / "post_grade_review.md").read_text()
            # Re-register connection for the review agent
            db_path = _find_duckdb(work_dir)
            if db_path:
                register_local_connection(task_id, str(db_path))
            review_result = asyncio.run(_run_agent(
                task_id, review_prompt, work_dir, model, max_turns=60,
                continue_conversation=True,
            ))
            if db_path:
                delete_local_connection(task_id)
            log(f"Post-grade review: {review_result.get('turns', '?')} turns")
        except Exception as e:
            log(f"Post-grade review error: {e}", "WARN")

    # ── Save audit trail ──────────────────────────────────────────────────────
    try:
        run_id = save_single_task_run(
            instance_id=task_id,
            suite="ade-bench",
            model=model,
            passed=passed,
            elapsed_seconds=total_elapsed,
            work_dir=work_dir,
        )
        log(f"Audit saved: {run_id}")
    except Exception as e:
        log(f"Audit save failed: {e}", "WARN")

    result = {
        "task_id": task_id,
        "passed": passed,
        "details": details,
        "turns": agent_result.get("turns", 0),
        "elapsed": total_elapsed,
        "difficulty": task["difficulty"],
    }

    # Write task_result.json
    (work_dir / "task_result.json").write_text(json.dumps(result, indent=2))

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
