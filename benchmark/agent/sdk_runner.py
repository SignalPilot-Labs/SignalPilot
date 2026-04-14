"""Thin wrapper around claude_agent_sdk.query with retry + logging."""

from __future__ import annotations

import asyncio
import json
import time
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
from claude_agent_sdk._errors import ClaudeSDKError, ProcessError

from ..core.logging import log, log_separator
from ..core.mcp import load_mcp_servers

SKILL_TOOL_NAMES = ("dbt-workflow", "dbt-verification", "dbt-debugging", "duckdb-sql")


async def run_sdk_agent(
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
        mcp_servers=load_mcp_servers(),
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

        except (ProcessError, ClaudeSDKError) as e:
            err_str = str(e)
            stderr_str = getattr(e, "stderr", "") or ""
            is_overloaded = (
                "529" in err_str or "overloaded" in err_str.lower()
                or "529" in stderr_str or "overloaded" in stderr_str.lower()
            )
            if is_overloaded and attempt < max_retries:
                log(f"API overloaded ({label}, attempt {attempt}/{max_retries}): {err_str[:200]}", "WARN")
                wait = 30 * attempt
                log(f"Retrying in {wait}s...")
                await asyncio.sleep(wait)
                continue
            if is_overloaded:
                log(f"API overloaded after {max_retries} retries ({label}) — giving up", "ERROR")
            else:
                log(f"Agent error ({label}): {e}", "ERROR")
            return {
                "success": False, "messages": messages, "tool_calls": tool_calls,
                "turns": turn_count, "elapsed": time.monotonic() - start_time,
            }

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
                return {
                    "success": False, "messages": messages, "tool_calls": tool_calls,
                    "turns": turn_count, "elapsed": time.monotonic() - start_time,
                }

        elapsed = time.monotonic() - start_time
        return {
            "success": success, "messages": messages, "tool_calls": tool_calls,
            "turns": turn_count, "elapsed": elapsed,
        }

    return {"success": False, "messages": [], "tool_calls": [], "turns": 0, "elapsed": 0.0}


async def run_quick_fix_agent(fix_prompt: str, work_dir: Path, model: str) -> bool:
    """Run a fix agent after a failed dbt run. Safety cap only — no budget."""
    log("Running quick-fix agent...")
    result = await run_sdk_agent(fix_prompt, work_dir, model, max_turns=200, timeout=1800, label="quick-fix")
    log("Fix agent completed" if result["success"] else "Fix agent failed")
    return result["success"]


async def run_value_verify_agent(verify_prompt: str, work_dir: Path, model: str) -> bool:
    """Run a value-verification agent. Safety cap only — no budget."""
    log("Running value-verification agent...")
    result = await run_sdk_agent(verify_prompt, work_dir, model, max_turns=200, timeout=1800, label="value-verify")
    log("Value-verify agent completed")
    return result["success"]


async def run_name_fix_agent(name_fix_prompt: str, work_dir: Path, model: str) -> bool:
    """Run an agent to fix missing table names. Safety cap only — no budget."""
    log("Running table-name fix agent...")
    result = await run_sdk_agent(name_fix_prompt, work_dir, model, max_turns=200, timeout=1200, label="name-fix")
    log("Name-fix agent completed" if result["success"] else "Name-fix agent failed")
    return result["success"]
