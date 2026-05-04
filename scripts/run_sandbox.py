#!/usr/bin/env python3
"""Console runner for the SignalPilot sandbox agent.

Connects to a running sandbox container, starts a Claude Code session
with the SignalPilot plugin and dbt project, and streams output to stdout.

Usage:
    # Start the stack first:
    docker compose up -d db gateway sandbox

    # Run the sandbox agent:
    SANDBOX_URL=http://localhost:8081 \
    SANDBOX_SECRET=dev-secret-change-me \
    python scripts/run_sandbox.py
"""

import asyncio
import json
import os
import signal
import sys
import time

# Allow importing sandbox_client from the repo
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "workspaces", "agent"))

from sandbox_client import SandboxClient  # noqa: E402

SANDBOX_URL = os.environ.get("SANDBOX_URL", "http://localhost:8081")
SANDBOX_SECRET = os.environ.get("SANDBOX_SECRET", "dev-secret-change-me")

SESSION_OPTIONS = {
    "model": os.environ.get("SANDBOX_MODEL", "claude-sonnet-4-6"),
    "fallback_model": None,
    "effort": "high",
    "system_prompt": {
        "type": "text",
        "preset": "default",
        "append": (
            "You are a dbt developer working in /home/agentuser/workdir. "
            "A dbt project is already set up with source definitions pointing "
            "at a Postgres database with e-commerce data (raw_ecommerce schema). "
            "You have access to the SignalPilot MCP tools for querying the database "
            "and exploring schemas. Use dbt to build models and analyze data."
        ),
    },
    "permission_mode": "bypassPermissions",
    "cwd": "/home/agentuser/workdir",
    "add_dirs": ["/opt/workspaces"],
    "setting_sources": ["project"],
    "max_budget_usd": float(os.environ.get("SANDBOX_BUDGET", "5.0")),
    "include_partial_messages": True,
    "initial_prompt": os.environ.get(
        "SANDBOX_PROMPT",
        (
            "1. Run `dbt debug` to verify the database connection.\n"
            "2. Explore the available source tables using the SignalPilot MCP tools.\n"
            "3. Build a staging model for customers.\n"
            "4. Create a mart model that joins customers with their orders and payments.\n"
            "5. Run `dbt run` to materialize the models.\n"
            "6. Query the mart model to show top 10 customers by total spend."
        ),
    ),
    "run_id": f"sandbox-v0-{int(time.time())}",
    "github_repo": "",
    "branch_name": "",
    "mcp_servers": {
        "signalpilot": {
            "type": "http",
            "url": os.environ.get("MCP_URL", "http://gateway:3300/mcp"),
        },
    },
}


def _print_event(event: dict) -> None:
    """Print a formatted SSE event to stdout."""
    event_type = event.get("event", "unknown")
    data = event.get("data", {})

    if event_type == "assistant_message":
        for block in data.get("content", []):
            btype = block.get("type")
            if btype == "text":
                print(block["text"], end="", flush=True)
            elif btype == "thinking":
                thinking = block.get("thinking", "")
                if thinking:
                    print(f"\n[thinking] {thinking[:300]}", flush=True)
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = json.dumps(block.get("input", {}), default=str)
                if len(inp) > 200:
                    inp = inp[:200] + "..."
                print(f"\n[tool] {name}({inp})", flush=True)

    elif event_type == "result":
        cost = data.get("total_cost_usd", 0)
        turns = data.get("num_turns", 0)
        print(f"\n\n--- Session complete. Cost: ${cost:.4f} | Turns: {turns} ---")

    elif event_type in ("session_end", "session_error"):
        print(f"\n--- {event_type}: {json.dumps(data)} ---")

    elif event_type in ("tool_use", "tool_done"):
        pass  # hook events, already printed via assistant_message

    elif event_type in ("end_round", "end_session", "end_session_denied"):
        print(f"\n[gate] {event_type}: {json.dumps(data)}")

    elif event_type == "rate_limit":
        print(f"\n[rate_limit] {json.dumps(data)}")

    elif event_type in ("subagent_start", "subagent_stop"):
        agent_id = data.get("agent_id", "?")
        print(f"\n[{event_type}] {agent_id}")


async def _wait_for_health(client: SandboxClient, timeout: float = 60) -> None:
    """Poll sandbox health until ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            health = await client.health()
            print(f"Sandbox healthy: {health}")
            return
        except Exception:
            await asyncio.sleep(2)
    raise TimeoutError(f"Sandbox not healthy after {timeout}s")


async def main() -> None:
    client = SandboxClient(SANDBOX_URL, SANDBOX_SECRET)
    session_id = None

    async def _shutdown() -> None:
        nonlocal session_id
        if session_id:
            print("\nStopping session...")
            try:
                await client.session.stop(session_id)
            except Exception:
                pass
        await client.close()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(_shutdown()))

    try:
        print(f"Connecting to sandbox at {SANDBOX_URL}...")
        await _wait_for_health(client)

        print("Starting session...")
        session_id = await client.session.start(SESSION_OPTIONS)
        print(f"Session started: {session_id}\n{'='*60}\n")

        async for event in client.session.stream_events(session_id):
            _print_event(event)
            if event.get("event") in ("session_end", "session_error", "result"):
                break

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        raise
    finally:
        await _shutdown()


if __name__ == "__main__":
    asyncio.run(main())
