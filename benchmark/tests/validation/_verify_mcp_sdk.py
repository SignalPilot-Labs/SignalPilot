"""
Diagnostic: spawn the SignalPilot MCP the exact way run_dbt_local.py does,
via the claude_agent_sdk, and capture EVERY message type the SDK emits so we
can see whether MCP tools reach the agent and what happens when it tries to
call them.

Run from repo root:
    python -m benchmark.tests.validation._verify_mcp_sdk
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

# Force utf-8 stdout on Windows so the unicode icons in tool output don't crash us.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

GATEWAY_SRC = PROJECT_ROOT / "signalpilot" / "gateway"
CHINOOK_CANONICAL = os.environ.get(
    "SPIDER2_DBT_DIR",
    str(PROJECT_ROOT / "benchmark" / "test-env"),
) + "/examples/chinook001"


def _truncate(s: str, n: int = 800) -> str:
    if len(s) <= n:
        return s
    return s[:n] + f"... [+{len(s) - n} chars]"


async def main() -> int:
    # Claude Code CLI strips `cwd` from MCP configs and runs the child from
    # its own working directory, so we use PYTHONPATH instead of cwd to let
    # `python -m gateway.mcp_server` resolve the package.
    child_env = {
        **os.environ,
        "SP_GATEWAY_URL": "http://localhost:3300",
        "PYTHONPATH": (
            str(GATEWAY_SRC) + os.pathsep + os.environ.get("PYTHONPATH", "")
        ).rstrip(os.pathsep),
    }
    mcp_config = {
        "signalpilot": {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "gateway.mcp_server"],
            "env": child_env,
        }
    }

    system_prompt = (
        "You have access to MCP tools under the mcp__signalpilot__* namespace. "
        "Call mcp__signalpilot__dbt_project_map with project_dir set to the path "
        "the user gives you, using focus='work_order'. "
        "After you get the result, print exactly 'DONE' and stop."
    )

    user_prompt = (
        f"Call mcp__signalpilot__dbt_project_map now with "
        f'project_dir="{CHINOOK_CANONICAL}" and focus="work_order". '
        f"Then print DONE."
    )

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        model="claude-sonnet-4-6",
        max_turns=6,
        permission_mode="bypassPermissions",
        cwd=str(PROJECT_ROOT),
        mcp_servers=mcp_config,
    )

    print(f"Spawning claude_agent_sdk with MCP config: signalpilot @ {GATEWAY_SRC}")
    print(f"System prompt: {len(system_prompt)} chars")
    print(f"User prompt: {user_prompt}")
    print()

    msg_index = 0
    async for message in query(prompt=user_prompt, options=options):
        msg_index += 1
        cls = type(message).__name__
        print(f"── message #{msg_index}: {cls} ──")

        if isinstance(message, SystemMessage):
            # System messages carry init info and tool metadata from Claude Code.
            for attr in ("subtype", "data"):
                val = getattr(message, attr, None)
                if val is not None:
                    print(f"  {attr}: {_truncate(str(val), 1200)}")

        elif isinstance(message, AssistantMessage):
            for i, block in enumerate(message.content):
                bcls = type(block).__name__
                if isinstance(block, TextBlock):
                    print(f"  [{i}] TextBlock: {_truncate(block.text, 600)}")
                elif isinstance(block, ToolUseBlock):
                    print(f"  [{i}] ToolUseBlock: name={block.name!r}")
                    print(f"       input: {_truncate(str(block.input), 400)}")
                else:
                    print(f"  [{i}] {bcls}: {_truncate(str(block), 400)}")

        elif isinstance(message, UserMessage):
            # UserMessage is where ToolResultBlocks live.
            content = getattr(message, "content", None)
            if isinstance(content, list):
                for i, block in enumerate(content):
                    bcls = type(block).__name__
                    if isinstance(block, ToolResultBlock):
                        result = getattr(block, "content", block)
                        is_error = getattr(block, "is_error", None)
                        print(f"  [{i}] ToolResultBlock (is_error={is_error}):")
                        print(f"       {_truncate(str(result), 1000)}")
                    else:
                        print(f"  [{i}] {bcls}: {_truncate(str(block), 400)}")
            else:
                print(f"  content: {_truncate(str(content), 600)}")

        elif isinstance(message, ResultMessage):
            for attr in ("subtype", "duration_ms", "num_turns", "total_cost_usd", "usage", "is_error"):
                val = getattr(message, attr, None)
                if val is not None:
                    print(f"  {attr}: {val}")

        else:
            print(f"  raw: {_truncate(str(message), 600)}")

        print()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
