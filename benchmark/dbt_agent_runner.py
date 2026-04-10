"""
DBT benchmark agent runner — runs INSIDE the Docker container.

Uses Claude Agent SDK to complete a dbt project task.
- Task files at /workspace
- Skills loaded from /workspace/skills/*.md
- Database access goes through SignalPilot MCP (schema exploration, queries)
- File writing (dbt SQL models) uses built-in Write/Bash tools

Usage (called by entrypoint.sh):
    python /app/dbt_agent_runner.py --instance-id chinook001 --model claude-opus-4-6
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

WORKSPACE = Path("/workspace")
GATEWAY_URL = os.environ.get("SP_GATEWAY_URL", "http://host.docker.internal:3300")


# ── SignalPilot connection registration ──────────────────────
def register_duckdb_connection(instance_id: str, db_path: str) -> bool:
    """Register the task's DuckDB file as a SignalPilot connection via gateway API."""
    import urllib.request
    import urllib.error

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
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        if e.code == 409:  # already exists
            return True
        log(f"Failed to register connection: {e.code} {e.reason}", "WARN")
        return False
    except Exception as e:
        log(f"Failed to register connection: {e}", "WARN")
        return False


# ── Logging helpers ──────────────────────────────────────────
def log(msg: str, level: str = "INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def log_separator(title: str = ""):
    print(f"\n{'='*60}", flush=True)
    if title:
        print(f"  {title}", flush=True)
        print(f"{'='*60}", flush=True)


def collect_project_context(project_dir: Path) -> str:
    """Read all files in the dbt project to build context for the agent."""
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
    """Build the system prompt for the dbt benchmark agent."""
    prompt = f"""You are a data scientist proficient in database, SQL and DBT Project.
You are working in /workspace, which contains a DuckDB-based dbt project.

## Task
{instruction}

## Database Access
You have access to SignalPilot MCP tools for database exploration and queries.
The DuckDB database is registered as connection '{instance_id}'.

Use these tools to explore the database:
- `mcp__signalpilot__list_tables` — list all tables in the database
- `mcp__signalpilot__describe_table` — get column details for a table
- `mcp__signalpilot__explore_table` — deep-dive with sample values
- `mcp__signalpilot__query_database` — run SQL queries (read-only)
- `mcp__signalpilot__schema_overview` — quick overview of the whole database
- `mcp__signalpilot__find_join_path` — find how to join two tables

You also have file tools (Read, Write, Glob, Grep) and Bash for running dbt commands.

## DBT Project Hints
1. Read the dbt project files. Your task is to write SQL queries for data transformation.
2. Use SignalPilot tools to explore the DuckDB database (schema, sample data, relationships).
3. Review the YAML files to understand task requirements and identify which model SQLs are incomplete.
4. The project is unfinished — identify models defined in .yml but missing .sql files and write them.
5. Do NOT modify .yml files — write correct SQL based on the existing YAML definitions.
6. After writing all required SQL, run `dbt deps && dbt run` via Bash to update the database.
7. Verify new data models using SignalPilot query_database to check they match YAML definitions.
8. You only need to CREATE new SQL files according to the YAML files, not modify existing ones (unless clearly unfinished).
9. Use DuckDB-compatible SQL syntax (not PostgreSQL, not MySQL).
10. Use dbt ref() and source() macros correctly.

## Current Project Files
{project_context}

## Instructions
1. Explore the database schema using SignalPilot tools (list_tables, describe_table)
2. Identify which .yml files don't have corresponding .sql files — those are the models you need to create
3. Read existing SQL files to understand naming conventions and patterns
4. Write each missing .sql file using the Write tool
5. Run `dbt deps && dbt run` via Bash to validate
6. If dbt run fails, read the error, fix the SQL, and re-run
7. Verify the models using SignalPilot query_database"""

    return prompt


def build_user_prompt(instruction: str) -> str:
    return (
        f"Complete this dbt project. The task is: {instruction}\n\n"
        f"Identify which models have .yml definitions but no .sql files, and write the SQL for each one. "
        f"Then run `dbt deps && dbt run` to validate."
    )


async def run_agent(instance_id: str, instruction: str, model: str = "claude-opus-4-6", max_turns: int = 200) -> dict:
    """Run the Claude agent to complete the dbt task."""

    # Log skills in .claude/skills/ (Claude Code loads these natively)
    skills_dir = WORKSPACE / ".claude" / "skills"
    if skills_dir.exists():
        skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
        log(f"Skills: {len(skill_dirs)} in .claude/skills/ (loaded by Claude Code)")
        for d in skill_dirs:
            log(f"  - {d.name}")
    else:
        log("No .claude/skills/ directory found")

    # Register DuckDB with SignalPilot (both gateway API and local MCP store)
    duckdb_files = list(WORKSPACE.glob("*.duckdb"))
    if duckdb_files:
        db_path = str(duckdb_files[0])
        log(f"Registering DuckDB connection '{instance_id}' -> {db_path}")

        # Register with host gateway API
        if register_duckdb_connection(instance_id, db_path):
            log("  Connection registered with gateway API")
        else:
            log("  Could not register with gateway API", "WARN")

        # Register in local MCP store so the stdio MCP server can find it
        try:
            mcp_cwd = os.environ.get("SIGNALPILOT_MCP_CWD", "/signalpilot")
            import sys
            sys.path.insert(0, mcp_cwd)
            from gateway.store import create_connection, get_connection
            from gateway.models import ConnectionCreate, DBType
            if not get_connection(instance_id):
                create_connection(ConnectionCreate(
                    name=instance_id,
                    db_type=DBType.duckdb,
                    database=db_path,
                    description=f"Spider2-DBT: {instance_id}",
                ))
            log("  Connection registered in local MCP store")
        except Exception as e:
            log(f"  Could not register in local store: {e}", "WARN")

    # Collect project context
    log("Collecting project context...")
    project_context = collect_project_context(WORKSPACE)
    log(f"Project context: {len(project_context)} chars from workspace files")

    system_prompt = build_system_prompt(instruction, project_context, instance_id)
    user_prompt = build_user_prompt(instruction)
    log(f"System prompt: {len(system_prompt)} chars")
    log(f"User prompt: {user_prompt[:200]}")

    # Log files in workspace (skip dbt_packages, .claude, __pycache__)
    log("Workspace project files:")
    for f in sorted(WORKSPACE.rglob("*")):
        if f.is_file() and ".duckdb" not in f.suffix:
            rel = f.relative_to(WORKSPACE)
            rel_str = str(rel)
            if any(skip in rel_str for skip in ("dbt_packages", ".claude", "__pycache__", "target", "logs", "skills")):
                continue
            log(f"  {rel} ({f.stat().st_size} bytes)")

    # Configure SignalPilot MCP server
    mcp_cwd = os.environ.get("SIGNALPILOT_MCP_CWD", "/signalpilot")
    use_mcp = os.path.exists(os.path.join(mcp_cwd, "gateway", "mcp_server.py"))

    mcp_config = None
    if use_mcp:
        mcp_config = {
            "signalpilot": {
                "type": "stdio",
                "command": "python",
                "args": ["-m", "gateway.mcp_server"],
                "cwd": mcp_cwd,
                "env": {
                    "SP_GATEWAY_URL": GATEWAY_URL,
                },
            }
        }
        log(f"MCP config: signalpilot stdio server at {mcp_cwd}")
        log(f"  gateway_url={GATEWAY_URL}")
    else:
        log("SignalPilot MCP not available (gateway code not found at %s)" % mcp_cwd, "WARN")

    # No max_budget_usd and no allowed_tools whitelist — the agent gets every
    # built-in tool, every SignalPilot MCP tool, the Skill tool for loaded
    # benchmark skills, and unbounded spend. The only ceiling is max_turns.
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=model,
        max_turns=max_turns,
        permission_mode="bypassPermissions",
        cwd=str(WORKSPACE),
        **({"mcp_servers": mcp_config} if mcp_config else {}),
        debug_stderr=True,
    )

    messages = []
    tool_calls = []
    turn_count = 0
    start_time = time.monotonic()

    log_separator(f"AGENT STARTING  model={model}  max_turns={max_turns} (safety cap only)")

    try:
        async for message in query(prompt=user_prompt, options=options):
            elapsed = time.monotonic() - start_time

            if isinstance(message, AssistantMessage):
                turn_count += 1
                log(f"─── Turn {turn_count} ({elapsed:.1f}s) ───")
                for block in message.content:
                    if isinstance(block, TextBlock):
                        # Print full text, not truncated
                        for line in block.text.split("\n"):
                            log(f"  AGENT: {line}")
                        messages.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_input_str = json.dumps(block.input, ensure_ascii=False)
                        log(f"  TOOL_USE: {block.name}")
                        # Print full tool input for debugging (truncate at 500 chars)
                        if len(tool_input_str) > 500:
                            log(f"    input: {tool_input_str[:500]}...")
                        else:
                            log(f"    input: {tool_input_str}")
                        tool_calls.append({"name": block.name, "input": block.input, "turn": turn_count})
                    elif isinstance(block, ToolResultBlock):
                        result_str = str(block.content) if hasattr(block, 'content') else str(block)
                        if len(result_str) > 1000:
                            log(f"  TOOL_RESULT: {result_str[:1000]}...")
                        else:
                            log(f"  TOOL_RESULT: {result_str}")

            elif isinstance(message, ResultMessage):
                log(f"AGENT FINISHED after {turn_count} turns, {elapsed:.1f}s")
                if hasattr(message, 'cost_usd'):
                    log(f"  Cost: ${getattr(message, 'cost_usd', 'N/A')}")
                if hasattr(message, 'usage'):
                    log(f"  Usage: {getattr(message, 'usage', 'N/A')}")

    except Exception as e:
        log(f"AGENT ERROR: {e}", "ERROR")
        traceback.print_exc()
        return {"error": str(e), "messages": messages, "tool_calls": tool_calls}

    elapsed = time.monotonic() - start_time
    log_separator(f"AGENT COMPLETE  turns={turn_count}  tools={len(tool_calls)}  elapsed={elapsed:.1f}s")

    # Log what files were created/modified
    log("Post-agent workspace files:")
    for f in sorted(WORKSPACE.rglob("*.sql")):
        rel = f.relative_to(WORKSPACE)
        log(f"  SQL: {rel} ({f.stat().st_size} bytes)")

    return {"messages": messages, "tool_calls": tool_calls, "elapsed": elapsed, "turns": turn_count}


def run_dbt() -> tuple[bool, str]:
    """Run dbt deps + dbt run in the workspace."""
    log_separator("FINAL DBT VALIDATION (post-agent)")

    try:
        log("Running: dbt deps")
        deps = subprocess.run(
            ["dbt", "deps"],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=120,
        )
        for line in (deps.stdout + deps.stderr).strip().split("\n"):
            if line.strip():
                log(f"  dbt deps: {line}")

        log("Running: dbt run")
        result = subprocess.run(
            ["dbt", "run"],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + "\n" + result.stderr
        for line in output.strip().split("\n"):
            if line.strip():
                log(f"  dbt run: {line}")

        log(f"dbt run exit code: {result.returncode}")
        return result.returncode == 0, output
    except Exception as e:
        log(f"dbt run error: {e}", "ERROR")
        return False, str(e)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--model", default="claude-opus-4-6")
    parser.add_argument("--max-turns", type=int, default=200)
    args = parser.parse_args()

    log_separator(f"Spider2-DBT Benchmark: {args.instance_id}")
    log(f"Model: {args.model}")
    log(f"Max turns: {args.max_turns}")
    log(f"Workspace: {WORKSPACE}")
    log(f"Python: {sys.version}")

    # Check workspace
    log("Checking workspace...")
    ws_files = list(WORKSPACE.iterdir())
    log(f"  {len(ws_files)} items in workspace root")
    for f in ws_files:
        log(f"  {'DIR ' if f.is_dir() else 'FILE'} {f.name}")

    # Run agent
    result = await run_agent(
        instance_id=args.instance_id,
        instruction=args.instruction,
        model=args.model,
        max_turns=args.max_turns,
    )

    if "error" in result:
        log(f"AGENT FAILED: {result['error']}", "ERROR")
        result_path = WORKSPACE / "agent_result.json"
        result_path.write_text(json.dumps({
            "success": False,
            "error": result["error"],
            "tool_calls": result.get("tool_calls", []),
        }, indent=2))
        sys.exit(1)

    # Final dbt validation (agent should have run dbt already, but verify)
    dbt_ok, dbt_output = run_dbt()

    # Log DuckDB contents after dbt run
    log("Checking DuckDB tables after dbt run:")
    try:
        import duckdb
        for db_file in WORKSPACE.glob("*.duckdb"):
            con = duckdb.connect(str(db_file), read_only=True)
            tables = con.execute("SHOW TABLES").fetchall()
            log(f"  {db_file.name}: {len(tables)} tables")
            for t in tables:
                try:
                    count = con.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
                    log(f"    {t[0]}: {count} rows")
                except Exception as e:
                    log(f"    {t[0]}: ERROR - {e}")
            con.close()
    except Exception as e:
        log(f"  DuckDB inspection error: {e}", "WARN")

    # Write result for host to read
    result_data = {
        "success": dbt_ok,
        "agent_elapsed": result.get("elapsed", 0),
        "agent_turns": result.get("turns", 0),
        "tool_calls": result.get("tool_calls", []),
        "dbt_output": dbt_output,
        "messages": result.get("messages", []),
    }
    result_path = WORKSPACE / "agent_result.json"
    result_path.write_text(json.dumps(result_data, indent=2))

    log_separator(f"DBT RUN: {'SUCCEEDED' if dbt_ok else 'FAILED'}")


if __name__ == "__main__":
    asyncio.run(main())
