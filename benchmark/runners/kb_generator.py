"""Knowledge Base Generator Runner.

Runs the dbt-knowledgebase skill on a task to populate the knowledge base
with project-specific entries. No gold comparison — completes when the
agent finishes proposing knowledge.

Usage:
    python -m benchmark.runners.kb_generator <instance_id> [--model claude-sonnet-4-6]
"""

from __future__ import annotations

import argparse
import asyncio
import time

from ..agent.sdk_runner import run_sdk_agent
from ..core.paths import MCP_CONFIG, PROMPTS_DIR, WORK_DIR, ensure_local_bin_on_path
from ..core.tasks import load_task
from ..core.workdir import prepare_workdir
from ..core.workdir import write_claude_md
from ..core.mcp import delete_local_connection, register_local_connection
from .direct import (
    log,
    log_separator,
    _mcp_sanity_check,
)


def build_kb_prompt(instance_id: str, instruction: str) -> str:
    """Build the knowledge base generation prompt."""
    return (
        f"Explore and map out this dbt project for my knowledge base. "
        f"The project is '{instance_id}'. Research every model, source table, "
        f"macro, and data pattern. Populate the knowledge base with everything "
        f"a future agent would need to build models correctly in this project."
    )


def build_kb_system_prompt() -> str:
    """System prompt for KB generation — loaded from prompts/kb_generation_system.md."""
    return (PROMPTS_DIR / "kb_generation_system.md").read_text()


async def _run_kb_generation(instance_id: str, model: str, max_turns: int) -> dict:
    """Run KB generation for a single task."""
    ensure_local_bin_on_path()

    # Load task
    t0 = time.monotonic()
    task = load_task(instance_id)
    instruction: str = task["instruction"]
    log(f"Task loaded in {time.monotonic() - t0:.2f}s")
    log(f"Instruction: {instruction}")

    # Prepare workdir (same as benchmark — copies project files, runs dbt deps)
    log_separator("Step 1: Prepare workdir")
    work_dir = prepare_workdir(instance_id)

    # Write CLAUDE.md
    log_separator("Step 2: Write CLAUDE.md")
    write_claude_md(work_dir, instance_id, instruction)

    # Register connection — find the DuckDB file
    log_separator("Step 3: Register connection")
    connection_name = instance_id
    db_files = list(work_dir.glob("*.duckdb"))
    if not db_files:
        log("No DuckDB file found in workdir", "ERROR")
        return {"success": False}
    db_path = str(db_files[0])
    log(f"DuckDB: {db_path}")
    register_local_connection(connection_name, db_path)

    # Run agent
    log_separator("Step 4: Run KB generation agent")
    prompt = build_kb_prompt(instance_id, instruction)
    system_prompt = build_kb_system_prompt()

    t_agent = time.monotonic()
    try:
        agent_result = await run_sdk_agent(
            prompt,
            work_dir,
            model,
            max_turns,
            timeout=600,
            label="kb-generator",
            system_prompt=system_prompt,
        )
    except Exception as e:
        log(f"Agent error: {e}", "ERROR")
        agent_result = {"success": False, "transcript": [], "tool_calls": [], "messages": [], "turns": 0}

    elapsed = time.monotonic() - t_agent
    log(f"KB generation finished in {elapsed:.1f}s")

    # Count proposed knowledge entries from tool calls
    propose_calls = [
        tc for tc in agent_result.get("tool_calls", [])
        if "propose_knowledge" in str(tc.get("name", ""))
    ]
    log(f"Knowledge entries proposed: {len(propose_calls)}")

    # Cleanup connection
    delete_local_connection(connection_name)

    log_separator("DONE")
    return agent_result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate knowledge base entries for a dbt task"
    )
    parser.add_argument("instance_id", help="Task instance ID, e.g. reddit001")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Claude model")
    parser.add_argument("--max-turns", type=int, default=150, help="Max agent turns")
    args = parser.parse_args()

    log_separator(f"Knowledge Base Generation: {args.instance_id}")
    log(f"Model: {args.model}")
    log(f"Max turns: {args.max_turns}")
    log(f"MCP config: {MCP_CONFIG}")

    _mcp_sanity_check()

    asyncio.run(_run_kb_generation(args.instance_id, args.model, args.max_turns))


if __name__ == "__main__":
    main()
