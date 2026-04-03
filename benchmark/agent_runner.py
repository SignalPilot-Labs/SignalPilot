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
    UserMessage,
    query,
)

from .config import BenchmarkConfig, SIGNALPILOT_GATEWAY_URL, SIGNALPILOT_MCP_CWD
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
        "You are a SQL expert tasked with answering a natural language question by querying a SQLite database.",
        "",
        "## Instructions",
        f"- The database is registered as connection '{task.connection_name}' in SignalPilot",
        "- Use `query_database` to run SQL queries (read-only, governed by SignalPilot)",
        "- Use `list_tables` or `describe_table` for schema exploration",
        "- Your goal is to produce the CORRECT result set that answers the question",
        "",
        "## Approach (follow this EXACTLY)",
        "1. PLAN: Before any SQL, state: (a) what columns the answer needs, (b) how many rows, (c) what units",
        "2. EXPLORE: use `list_tables` then `describe_table` for relevant tables, sample with LIMIT 3",
        "3. WRITE SQL: SELECT only the columns the question asks for — no extra columns!",
        "4. EXECUTE: run with `query_database`, verify result shape matches your plan",
        "5. VERIFY: check row count, column count, numeric scale/units, aggregation level",
        "6. If results look wrong, iterate — check data types, NULLs, joins, filters",
        "",
        "## CRITICAL Rules",
        "- SELECT ONLY the columns the question asks for. Extra columns = WRONG answer.",
        "- For percentages/rates: output as 0-100 (e.g., 45.5), NOT as 0-1 fraction",
        "- For proportions/shares: output as 0-1 (e.g., 0.455), NOT as percentage",
        "- Always use CAST(x AS REAL) for division to avoid integer truncation",
        "- Never round unless the question explicitly asks for rounding",
        "- If your query returns 0 rows, something is wrong — check your filters",
        "",
        "## SQLite Tips",
        "- Use `strftime('%Y-%m', date_col)` for date grouping, NOT DATE_FORMAT",
        "- Use `CAST(x AS REAL)` for decimal division, not just x/y",
        "- Use `COALESCE(col, 0)` to handle NULLs in aggregations",
        "- PRAGMA table_info(table_name) shows column names and types",
        "- Use `GROUP BY` with `HAVING` for filtered aggregations",
        "- For ranking, use `ROW_NUMBER() OVER (ORDER BY ...)` or simple ORDER BY + LIMIT",
        "",
        "## Output Format",
        "After you have the final correct result, output EXACTLY this block:",
        "```sql",
        "-- FINAL SQL",
        "<your final SQL query here>",
        "```",
        "",
        "The results from your last `query_database` call are captured automatically.",
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


def _sql_matches(sql_a: str, sql_b: str) -> bool:
    """Check if two SQL strings match (ignoring whitespace/comments)."""
    def _normalize(s: str) -> str:
        s = re.sub(r'--[^\n]*', '', s)
        s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)
        return ' '.join(s.split()).strip().rstrip(';').lower()
    return _normalize(sql_a) == _normalize(sql_b)


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
    """Register a SQLite database in the local SignalPilot store.

    The benchmark MCP server runs locally (stdio) and reads connections from
    the local store, so we register directly rather than via the gateway API.
    """
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
    except Exception as e:
        print(f"Error registering connection in local store: {e}")
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

    # Configure MCP server for SignalPilot (stdio transport).
    # Use bash wrapper to set cwd since McpStdioServerConfig lacks a cwd field.
    mcp_config = {
        "signalpilot": {
            "type": "stdio",
            "command": "/bin/bash",
            "args": ["-c", f"cd {SIGNALPILOT_MCP_CWD} && exec python -m gateway.mcp_server"],
            "env": {
                "SP_GATEWAY_URL": SIGNALPILOT_GATEWAY_URL,
            },
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
            "mcp__signalpilot__describe_table",
            "mcp__signalpilot__list_tables",
            "mcp__signalpilot__execute_code",
            "mcp__signalpilot__sandbox_status",
        ],
        disallowed_tools=["Write", "Edit", "Bash", "Agent"],
    )

    # Track the last tool_use name to correlate with tool results
    last_tool_name = ""
    # Keep all query results to pick the best one at the end
    all_query_results: list[tuple[str, str]] = []  # (sql, result_text)

    try:
        async for message in query(prompt=user_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        output.messages.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        last_tool_name = block.name
                        # Track tool usage
                        if block.name == "mcp__signalpilot__query_database":
                            sql = block.input.get("sql", "")
                            if sql:
                                output.final_sql = sql
                        output.turns_used += 1

            elif isinstance(message, UserMessage):
                # Tool results arrive in UserMessage blocks (not AssistantMessage)
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        # content is str | list[dict] | None
                        content = block.content
                        if isinstance(content, list):
                            # List of content items — concatenate text parts
                            text = " ".join(
                                item.get("text", "") for item in content
                                if isinstance(item, dict)
                            )
                        elif isinstance(content, str):
                            text = content
                        else:
                            text = ""

                        # MCP tool results may be JSON-wrapped: {"result":"..."}
                        if text.startswith("{"):
                            try:
                                parsed = json.loads(text)
                                if isinstance(parsed, dict) and "result" in parsed:
                                    text = parsed["result"]
                            except (json.JSONDecodeError, TypeError):
                                pass

                        if not text:
                            continue

                        if "Query blocked" in text:
                            output.governance_blocked = True
                            output.block_reason = text
                        elif last_tool_name == "mcp__signalpilot__query_database":
                            # Track all query results for later selection
                            all_query_results.append((output.final_sql, text))
                            output.final_result_text = text

            elif isinstance(message, ResultMessage):
                if hasattr(message, "usage"):
                    output.tokens_used = getattr(message.usage, "total_tokens", 0)

    except Exception as e:
        err_str = str(e)
        # If the agent already gathered query results before crashing, treat
        # this as a successful (partial) run rather than an error.
        if all_query_results and output.final_sql:
            # Agent ran and got results — just a crash at cleanup/end
            pass  # Fall through to normal result processing below
        # Retry on transient CLI/MCP failures (exit code 1, connection reset)
        elif ("exit code 1" in err_str or "Connection reset" in err_str) and output.turns_used < 3:
            print(f"    Retrying after transient error: {err_str[:80]}")
            await asyncio.sleep(2)
            output2 = AgentOutput()
            start2 = time.monotonic()
            try:
                async for message in query(prompt=user_prompt, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                output2.messages.append(block.text)
                            elif isinstance(block, ToolUseBlock):
                                last_tool_name = block.name
                                if block.name == "mcp__signalpilot__query_database":
                                    sql = block.input.get("sql", "")
                                    if sql:
                                        output2.final_sql = sql
                                output2.turns_used += 1
                    elif isinstance(message, UserMessage):
                        for block in message.content:
                            if isinstance(block, ToolResultBlock):
                                content = block.content
                                if isinstance(content, list):
                                    text = " ".join(
                                        item.get("text", "") for item in content
                                        if isinstance(item, dict)
                                    )
                                elif isinstance(content, str):
                                    text = content
                                else:
                                    text = ""
                                if text.startswith("{"):
                                    try:
                                        parsed = json.loads(text)
                                        if isinstance(parsed, dict) and "result" in parsed:
                                            text = parsed["result"]
                                    except (json.JSONDecodeError, TypeError):
                                        pass
                                if not text:
                                    continue
                                if "Query blocked" in text:
                                    output2.governance_blocked = True
                                    output2.block_reason = text
                                elif last_tool_name == "mcp__signalpilot__query_database":
                                    output2.final_result_text = text
                    elif isinstance(message, ResultMessage):
                        if hasattr(message, "usage"):
                            output2.tokens_used = getattr(message.usage, "total_tokens", 0)
                output2.execution_ms = (time.monotonic() - start2) * 1000
                if output2.final_result_text:
                    output2.result_rows = parse_query_result_to_rows(output2.final_result_text)
                if not output2.final_sql:
                    output2.final_sql = _extract_final_sql(output2.messages)
                return output2
            except Exception as e2:
                output.error = f"{type(e2).__name__}: {e2}"
        else:
            output.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    output.execution_ms = (time.monotonic() - start_time) * 1000

    # Try to extract final SQL from messages if not captured from tool calls
    if not output.final_sql:
        output.final_sql = _extract_final_sql(output.messages)

    # If the agent marked a FINAL SQL in its messages, find the corresponding
    # query result rather than blindly using the last one (which may be a
    # verification/exploratory query).
    final_marked_sql = _extract_final_sql(output.messages)
    if final_marked_sql and all_query_results:
        # Try to match the marked SQL to a captured query result
        for sql, result_text in reversed(all_query_results):
            if _sql_matches(sql, final_marked_sql):
                output.final_result_text = result_text
                output.final_sql = sql
                break

    # Parse result rows from the final result text
    if output.final_result_text:
        output.result_rows = parse_query_result_to_rows(output.final_result_text)

    return output


async def run_task_with_eval(
    task: TaskContext,
    config: BenchmarkConfig,
    gold_csv_path: Path | list[Path] | None = None,
    eval_config: dict | None = None,
) -> EvalResult:
    """Run a task and evaluate against gold standard.

    gold_csv_path may be a single Path, a list of variant Paths, or None.
    """
    from .eval import evaluate_task, load_gold_csv

    output = await run_task(task, config)

    # Normalise to list for uniform handling below
    if isinstance(gold_csv_path, list):
        gold_paths: list[Path] = [p for p in gold_csv_path if p.exists()]
    elif gold_csv_path is not None and gold_csv_path.exists():
        gold_paths = [gold_csv_path]
    else:
        gold_paths = []

    correct = False
    if gold_paths and output.result_rows:
        correct = evaluate_task(
            task.instance_id,
            output.result_rows,
            gold_paths,
            eval_config,
        )

    # Load gold rows from the first available variant for the report
    gold_rows = load_gold_csv(gold_paths[0]) if gold_paths else []

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
