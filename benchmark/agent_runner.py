"""
Agent runner — uses Claude Agent SDK to run Spider2 tasks through SignalPilot.

Each task:
1. Registers the SQLite DB as a SignalPilot connection
2. Creates a Claude agent session with SignalPilot MCP tools
3. Sends the NL question + external knowledge + skills
4. Agent explores schema, writes SQL, executes through governance
5. Captures the final SQL and result rows
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    query,
)

from .config import BenchmarkConfig, SIGNALPILOT_MCP_CWD
from .eval import EvalResult, parse_query_result_to_rows
from .skills import Skill, skills_to_prompt


@dataclass
class TaskContext:
    """Context for a single benchmark task."""
    instance_id: str
    question: str
    db_id: str
    db_path: str
    external_knowledge: str = ""
    skills_prompt: str = ""
    connection_name: str = ""


@dataclass
class AgentOutput:
    """Captured output from the agent's execution."""
    final_sql: str = ""
    final_result_text: str = ""
    result_rows: list[dict] = field(default_factory=list)
    turns_used: int = 0
    tokens_used: int = 0
    messages: list[str] = field(default_factory=list)
    error: str = ""
    governance_blocked: bool = False
    block_reason: str = ""
    execution_ms: float = 0.0


def _build_system_prompt(task: TaskContext, config: BenchmarkConfig) -> str:
    """Build the system prompt for the benchmark agent."""
    parts = [
        "You are a SQL expert tasked with answering a natural language question by querying a database.",
        "",
        "## Instructions",
        f"- The database is registered as connection '{task.connection_name}' in SignalPilot",
        "- Use `query_database` to run SQL queries (read-only, governed by SignalPilot)",
        "- Use `list_database_connections` to verify the connection exists",
        "- First explore the database schema to understand the tables and columns",
        "- Then write and execute SQL to answer the question",
        "- Your goal is to produce the CORRECT result set that answers the question",
        "",
        "## Approach",
        "1. List connections to confirm the database is available",
        "2. Explore schema: query sqlite_master or use PRAGMA table_info",
        "3. Sample data from relevant tables to understand formats",
        "4. Write your SQL query",
        "5. Execute it and verify the results make sense",
        "6. If results look wrong, iterate on your query",
        "",
        "## Output Format",
        "After you have the final correct result, output EXACTLY this block:",
        "```sql",
        "-- FINAL SQL",
        "<your final SQL query here>",
        "```",
        "",
        "Then output the results in a clearly marked block.",
        "If the query returns results through query_database, that is sufficient.",
    ]

    if task.external_knowledge:
        parts.extend([
            "",
            "## External Knowledge",
            task.external_knowledge,
        ])

    if task.skills_prompt:
        parts.extend(["", task.skills_prompt])

    return "\n".join(parts)


def _build_user_prompt(task: TaskContext) -> str:
    """Build the user prompt (the question) for the agent."""
    return (
        f"Database: {task.connection_name} (SQLite, db_id={task.db_id})\n\n"
        f"Question: {task.question}\n\n"
        "Please explore the database schema and write a SQL query to answer this question. "
        "Show me the final SQL and results."
    )


def _extract_final_sql(messages: list[str]) -> str:
    """Extract the final SQL from the agent's messages."""
    # Look for explicitly marked final SQL
    for msg in reversed(messages):
        match = re.search(r"```sql\s*\n--\s*FINAL\s*SQL\s*\n(.+?)```", msg, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Fall back to last SQL block
    for msg in reversed(messages):
        matches = re.findall(r"```sql\s*\n(.+?)```", msg, re.DOTALL)
        if matches:
            return matches[-1].strip()

    return ""


def _extract_query_results(messages: list[str]) -> list[dict[str, Any]]:
    """Extract the last query_database result from messages."""
    for msg in reversed(messages):
        rows = parse_query_result_to_rows(msg)
        if rows:
            return rows
    return []


async def register_sqlite_connection(
    connection_name: str,
    db_path: str,
    gateway_url: str = "http://localhost:3300",
) -> bool:
    """Register a SQLite database as a SignalPilot connection via the gateway API."""
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            # Check if connection already exists
            resp = await client.get(f"{gateway_url}/api/connections")
            if resp.status_code == 200:
                connections = resp.json()
                for conn in connections:
                    if conn.get("name") == connection_name:
                        return True  # Already registered

            # Register new connection
            resp = await client.post(
                f"{gateway_url}/api/connections",
                json={
                    "name": connection_name,
                    "db_type": "sqlite",
                    "database": db_path,
                    "description": f"Spider2 benchmark database: {connection_name}",
                },
            )
            return resp.status_code in (200, 201)
        except Exception as e:
            print(f"Warning: Could not register connection via API: {e}")
            # Fall back to direct store manipulation
            try:
                import sys
                sys.path.insert(0, str(Path(SIGNALPILOT_MCP_CWD)))
                from gateway.models import ConnectionCreate, DBType
                from gateway.store import create_connection, get_connection

                if get_connection(connection_name):
                    return True

                create_connection(ConnectionCreate(
                    name=connection_name,
                    db_type=DBType.sqlite,
                    database=db_path,
                    description=f"Spider2 benchmark: {connection_name}",
                ))
                return True
            except Exception as e2:
                print(f"Error registering connection: {e2}")
                return False


async def run_task(
    task: TaskContext,
    config: BenchmarkConfig,
) -> AgentOutput:
    """Run a single benchmark task using Claude Agent SDK."""
    output = AgentOutput()
    start_time = time.monotonic()

    system_prompt = _build_system_prompt(task, config)
    user_prompt = _build_user_prompt(task)

    # Configure MCP server for SignalPilot
    mcp_config = {
        "signalpilot": {
            "type": "stdio",
            "command": "python",
            "args": ["-m", "gateway.mcp_server"],
            "cwd": SIGNALPILOT_MCP_CWD,
        }
    }

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model=config.model,
        max_turns=config.max_turns,
        max_budget_usd=config.max_budget_usd,
        permission_mode="bypassPermissions",
        mcp_servers=mcp_config,
        allowed_tools=[
            "mcp__signalpilot__query_database",
            "mcp__signalpilot__list_database_connections",
            "mcp__signalpilot__execute_code",
            "mcp__signalpilot__sandbox_status",
        ],
        disallowed_tools=["Write", "Edit", "Bash", "Agent"],
    )

    try:
        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        output.messages.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        # Track tool usage
                        if block.name == "mcp__signalpilot__query_database":
                            sql = block.input.get("sql", "")
                            if sql:
                                output.final_sql = sql
                        output.turns_used += 1
                    elif isinstance(block, ToolResultBlock):
                        # Capture query results from tool responses
                        text = getattr(block, "text", "") or ""
                        if not text and hasattr(block, "content"):
                            text = str(block.content)
                        if text:
                            if "Query blocked" in text:
                                output.governance_blocked = True
                                output.block_reason = text
                            else:
                                output.final_result_text = text

            elif isinstance(message, ResultMessage):
                if hasattr(message, "usage"):
                    output.tokens_used = getattr(message.usage, "total_tokens", 0)

    except Exception as e:
        output.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    output.execution_ms = (time.monotonic() - start_time) * 1000

    # Parse result rows from the final result text
    if output.final_result_text:
        output.result_rows = parse_query_result_to_rows(output.final_result_text)

    # Try to extract final SQL from messages if not captured from tool calls
    if not output.final_sql:
        output.final_sql = _extract_final_sql(output.messages)

    return output


async def run_task_with_eval(
    task: TaskContext,
    config: BenchmarkConfig,
    gold_csv_path: Path | None = None,
    eval_config: dict | None = None,
) -> EvalResult:
    """Run a task and evaluate against gold standard."""
    from .eval import evaluate_task

    output = await run_task(task, config)

    correct = False
    if gold_csv_path and gold_csv_path.exists() and output.result_rows:
        correct = evaluate_task(
            task.instance_id,
            output.result_rows,
            gold_csv_path,
            eval_config,
        )

    # Load gold rows for the report
    from .eval import load_gold_csv
    gold_rows = load_gold_csv(gold_csv_path) if gold_csv_path and gold_csv_path.exists() else []

    return EvalResult(
        instance_id=task.instance_id,
        correct=correct,
        question=task.question,
        db_id=task.db_id,
        predicted_sql=output.final_sql,
        predicted_rows=output.result_rows,
        gold_rows=gold_rows,
        agent_messages=output.messages,
        error=output.error,
        execution_ms=output.execution_ms,
        turns_used=output.turns_used,
        tokens_used=output.tokens_used,
        governance_blocked=output.governance_blocked,
        block_reason=output.block_reason,
    )
