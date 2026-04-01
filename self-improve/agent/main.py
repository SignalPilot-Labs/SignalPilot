"""Self-improve agent orchestrator.

The agent container runs an HTTP server on port 8500 that waits for
start commands from the monitor UI. Each POST /start triggers a new
improvement run on a background task.

Control signals (stop, pause, inject, unlock) are delivered INSTANTLY
via an asyncio.Queue — no polling delay. The /kill endpoint cancels
the task immediately without waiting for the agent to wrap up.
"""

import asyncio
import json as _json
import os
import shutil
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)
from claude_agent_sdk.types import RateLimitEvent, StreamEvent, HookMatcher

from agent import db, hooks, git_ops, permissions, prompt, session_gate

import asyncpg


# =============================================================================
# Shared state
# =============================================================================
_current_run_id: str | None = None
_current_task: asyncio.Task | None = None
_signal_queue: asyncio.Queue | None = None  # Instant control signal delivery
_listener_task: asyncio.Task | None = None
_listener_conn: asyncpg.Connection | None = None


# =============================================================================
# Instant signal delivery via pg LISTEN + in-process queue
# =============================================================================

async def _start_signal_listener(run_id: str) -> None:
    """Start listening for pg_notify control signals for this run."""
    global _signal_queue, _listener_task, _listener_conn
    _signal_queue = asyncio.Queue()

    dsn = os.environ["AUDIT_DB_URL"]
    _listener_conn = await asyncpg.connect(dsn)

    def _on_notify(conn, pid, channel, payload):
        try:
            data = _json.loads(payload)
            if str(data.get("run_id")) == run_id:
                _signal_queue.put_nowait(data)
        except Exception:
            pass

    await _listener_conn.add_listener("control_signal", _on_notify)
    print(f"[agent] Listening for control signals (run {run_id[:8]})")


async def _stop_signal_listener() -> None:
    """Stop the pg listener."""
    global _listener_conn, _signal_queue
    if _listener_conn:
        try:
            await _listener_conn.remove_listener("control_signal", lambda *a: None)
            await _listener_conn.close()
        except Exception:
            pass
        _listener_conn = None
    _signal_queue = None


def _push_signal(signal: str, payload: str | None = None) -> None:
    """Push a signal directly to the queue (used by /stop, /kill endpoints)."""
    if _signal_queue:
        _signal_queue.put_nowait({"signal": signal, "payload": payload})


async def _drain_signal() -> dict | None:
    """Non-blocking check for a pending signal."""
    if not _signal_queue:
        return None
    try:
        return _signal_queue.get_nowait()
    except asyncio.QueueEmpty:
        return None


async def _wait_for_signal(timeout: float = 2.0) -> dict | None:
    """Wait up to timeout seconds for a signal."""
    if not _signal_queue:
        return None
    try:
        return await asyncio.wait_for(_signal_queue.get(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.QueueEmpty):
        return None


async def handle_pause(run_id: str) -> str | None:
    """Block until resume, inject, or stop signal arrives via the instant queue."""
    print("[agent] PAUSED — waiting for signal...")
    await db.update_run_status(run_id, "paused")
    await db.log_audit(run_id, "paused", {})

    while True:
        signal = await _wait_for_signal(timeout=5.0)
        if signal:
            sig = signal["signal"]
            if sig == "resume":
                print("[agent] RESUMED")
                await db.update_run_status(run_id, "running")
                return "resume"
            elif sig == "inject":
                payload = signal.get("payload", "")
                print(f"[agent] INJECTED: {payload[:100]}...")
                await db.update_run_status(run_id, "running")
                await db.log_audit(run_id, "prompt_injected", {"prompt": payload})
                return f"inject:{payload}"
            elif sig == "stop":
                print("[agent] STOP received while paused")
                await db.log_audit(run_id, "stop_requested", {"reason": signal.get("payload", "")})
                return "stop"
            elif sig == "unlock":
                session_gate.force_unlock()
                await db.update_run_status(run_id, "running")
                await db.log_audit(run_id, "session_unlocked", {})
                return "resume"


# =============================================================================
# Main agent run
# =============================================================================

async def run_agent(
    custom_prompt: str | None = None,
    max_budget: float = 50.0,
    duration_minutes: float = 0,
    base_branch: str = "main",
):
    """Execute one improvement run."""
    global _current_run_id

    model = os.environ.get("AGENT_MODEL", "claude-opus-4-20250514")

    # --- Git setup ---
    git_ops.setup_git_auth()
    branch_name = git_ops.get_branch_name()
    git_ops.create_branch(branch_name, base_branch=base_branch)
    print(f"[agent] Created branch: {branch_name} (from {base_branch})")

    # --- DB record ---
    run_id = await db.create_run(branch_name)
    _current_run_id = run_id
    print(f"[agent] Run ID: {run_id}")

    hooks.set_run_id(run_id)
    hooks.set_agent_role("worker")
    permissions.set_run_id(run_id)
    session_gate.configure(run_id, duration_minutes)
    session_mcp = session_gate.create_session_mcp_server()

    # --- Start instant signal listener ---
    await _start_signal_listener(run_id)

    duration_str = f"{duration_minutes}m" if duration_minutes > 0 else "unlimited"
    print(f"[agent] Duration: {duration_str}")

    await db.log_audit(run_id, "run_started", {
        "branch": branch_name,
        "base_branch": base_branch,
        "model": model,
        "max_budget_usd": max_budget,
        "duration_minutes": duration_minutes,
        "custom_prompt": custom_prompt[:200] if custom_prompt else None,
    })

    # --- Copy skills into cloned repo ---
    work_dir = git_ops.get_work_dir()
    skills_src = Path("/workspace/self-improve/.claude")
    skills_dst = Path(work_dir) / ".claude"
    if skills_src.exists():
        if skills_dst.exists():
            shutil.rmtree(skills_dst)
        shutil.copytree(skills_src, skills_dst)
        print(f"[agent] Copied skills to {skills_dst}")

    # --- SDK options ---
    options = ClaudeAgentOptions(
        model=model,
        effort="medium",
        system_prompt=prompt.build_system_prompt(
            custom_focus=custom_prompt,
            duration_minutes=duration_minutes,
        ),
        permission_mode="bypassPermissions",
        can_use_tool=permissions.check_tool_permission,
        cwd=work_dir,
        add_dirs=["/workspace", "/home/agentuser/research"],
        setting_sources=["project"],
        max_budget_usd=max_budget if max_budget > 0 else None,
        include_partial_messages=True,
        mcp_servers={
            "session_gate": session_mcp,
            "playwright": {
                "command": "playwright-mcp",
                "args": [],
            },
        },
        hooks={
            "PreToolUse": [HookMatcher(hooks=[hooks.pre_tool_use_hook])],
            "PostToolUse": [HookMatcher(hooks=[hooks.post_tool_use_hook])],
            "Stop": [HookMatcher(hooks=[hooks.stop_hook])],
        },
    )

    # --- Debug log ---
    debug_params = {
        "model": options.model,
        "effort": options.effort,
        "permission_mode": options.permission_mode,
        "cwd": str(options.cwd),
        "add_dirs": [str(d) for d in options.add_dirs] if options.add_dirs else [],
        "setting_sources": options.setting_sources,
        "max_budget_usd": options.max_budget_usd,
        "include_partial_messages": options.include_partial_messages,
        "mcp_servers": list(options.mcp_servers.keys()) if isinstance(options.mcp_servers, dict) else str(options.mcp_servers),
        "hooks_configured": list(options.hooks.keys()) if options.hooks else [],
        "has_can_use_tool": options.can_use_tool is not None,
        "system_prompt_type": options.system_prompt.get("type") if isinstance(options.system_prompt, dict) else type(options.system_prompt).__name__,
        "system_prompt_length": len(options.system_prompt.get("append", "")) if isinstance(options.system_prompt, dict) else None,
    }
    print(f"[agent] === SDK Configuration ===", flush=True)
    print(_json.dumps(debug_params, indent=2, default=str), flush=True)
    print(f"[agent] ========================", flush=True)
    await db.log_audit(run_id, "sdk_config", debug_params)

    # --- Run ---
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    pr_url = None
    final_status = "completed"
    max_rounds = 500

    try:
        async with ClaudeSDKClient(options=options) as client:
            initial = custom_prompt if custom_prompt else prompt.build_initial_prompt()
            await client.query(initial)
            print("[agent] Sent initial prompt")

            for round_num in range(max_rounds):
                # After CEO prompt, this round processes the CEO's response (tool calls tagged "ceo").
                # After CEO response completes, we switch back to worker.
                current_role = hooks._agent_role  # track what role is active
                print(f"[agent] Round {round_num + 1} [{current_role.upper()}] | Elapsed: {session_gate.elapsed_minutes():.0f}m | Remaining: {session_gate.time_remaining_str()}")

                rate_limited = False
                round_result = None
                should_stop = False

                # --- Per-round tracking for CEO summary ---
                round_tools: list[str] = []
                round_text_chunks: list[str] = []

                async for message in client.receive_response():
                    # --- Instant signal check (non-blocking) ---
                    signal = await _drain_signal()
                    if signal:
                        sig = signal["signal"]
                        if sig == "stop":
                            reason = signal.get("payload", "Operator stop")
                            print(f"[agent] INSTANT STOP: {reason}")
                            await client.interrupt()
                            await db.log_audit(run_id, "stop_requested", {"reason": reason, "instant": True})
                            final_status = "stopped"
                            should_stop = True
                            break
                        elif sig == "pause":
                            await client.interrupt()
                            async for _ in client.receive_response():
                                pass
                            result = await handle_pause(run_id)
                            if result == "stop":
                                final_status = "stopped"
                                should_stop = True
                                break
                            elif result == "resume":
                                await client.query(prompt.build_continuation_prompt())
                                break
                            elif result and result.startswith("inject:"):
                                await client.query(result[7:])
                                break
                        elif sig == "unlock":
                            session_gate.force_unlock()
                            await db.log_audit(run_id, "session_unlocked", {})
                        elif sig == "inject":
                            pass  # picked up between rounds

                    # --- StreamEvent ---
                    if isinstance(message, StreamEvent):
                        event_data = message.event or {}
                        if event_data.get("type") == "content_block_delta":
                            delta = event_data.get("delta", {})
                            dtype = delta.get("type", "")
                            if dtype == "text_delta" and delta.get("text"):
                                try:
                                    await db.log_audit(run_id, "llm_text", {"text": delta["text"][:2000], "agent_role": hooks._agent_role})
                                except Exception:
                                    pass
                            elif dtype == "thinking_delta" and delta.get("thinking"):
                                try:
                                    await db.log_audit(run_id, "llm_thinking", {"text": delta["thinking"][:2000], "agent_role": hooks._agent_role})
                                except Exception:
                                    pass
                        continue

                    # --- AssistantMessage ---
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                print(f"[agent] {block.text[:200].replace(chr(10), ' ')}")
                                round_text_chunks.append(block.text[:500])
                            elif isinstance(block, ThinkingBlock):
                                print(f"[agent] [thinking] {block.thinking[:100]}...")
                            elif isinstance(block, ToolUseBlock):
                                print(f"[agent] Tool: {block.name}")
                                round_tools.append(block.name)
                        if message.usage:
                            msg_input = message.usage.get("input_tokens", 0)
                            msg_output = message.usage.get("output_tokens", 0)
                            total_input_tokens += msg_input
                            total_output_tokens += msg_output
                            try:
                                await db.log_audit(run_id, "usage", {
                                    "input_tokens": msg_input,
                                    "output_tokens": msg_output,
                                    "total_input_tokens": total_input_tokens,
                                    "total_output_tokens": total_output_tokens,
                                    "cache_creation_input_tokens": message.usage.get("cache_creation_input_tokens", 0),
                                    "cache_read_input_tokens": message.usage.get("cache_read_input_tokens", 0),
                                })
                            except Exception:
                                pass

                    # --- RateLimitEvent ---
                    elif isinstance(message, RateLimitEvent):
                        info = message.rate_limit_info
                        await db.log_audit(run_id, "rate_limit", {
                            "status": info.status,
                            "resets_at": info.resets_at,
                            "utilization": info.utilization,
                        })
                        if info.status == "rejected":
                            if info.resets_at:
                                wait_sec = max(0, info.resets_at - time.time()) + 10
                                print(f"[agent] Rate limited. Waiting {wait_sec:.0f}s...")
                                await db.update_run_status(run_id, "rate_limited")
                                # Wait but check for stop signals every 2s
                                end_time = time.time() + min(wait_sec, 3600)
                                while time.time() < end_time:
                                    sig = await _wait_for_signal(timeout=2.0)
                                    if sig and sig["signal"] == "stop":
                                        final_status = "stopped"
                                        should_stop = True
                                        break
                                if should_stop:
                                    break
                                await db.update_run_status(run_id, "running")
                                rate_limited = True
                            else:
                                final_status = "rate_limited"
                                break

                    # --- ResultMessage ---
                    elif isinstance(message, ResultMessage):
                        round_result = message
                        if message.total_cost_usd:
                            total_cost = message.total_cost_usd
                        if message.usage:
                            total_input_tokens = message.usage.get("input_tokens", total_input_tokens)
                            total_output_tokens = message.usage.get("output_tokens", total_output_tokens)
                        await db.log_audit(run_id, "round_complete", {
                            "round": round_num + 1,
                            "turns": message.num_turns,
                            "cost_usd": message.total_cost_usd,
                            "elapsed_minutes": round(session_gate.elapsed_minutes(), 1),
                        })

                if should_stop:
                    break

                # --- Session ended via end_session tool ---
                if session_gate.has_ended():
                    print("[agent] Session ended via end_session tool")
                    final_status = "completed"
                    break

                # --- Between-round signal check ---
                signal = await _drain_signal()
                if signal:
                    sig = signal["signal"]
                    if sig == "stop":
                        await client.query(prompt.build_stop_prompt(signal.get("payload", "")))
                        async for msg in client.receive_response():
                            if isinstance(msg, ResultMessage) and msg.total_cost_usd:
                                total_cost = msg.total_cost_usd
                        final_status = "stopped"
                        break
                    elif sig == "pause":
                        result = await handle_pause(run_id)
                        if result == "stop":
                            final_status = "stopped"
                            break
                        elif result and result.startswith("inject:"):
                            await client.query(result[7:])
                            continue
                    elif sig == "inject":
                        payload = signal.get("payload", "")
                        if payload:
                            await db.log_audit(run_id, "prompt_injected", {"prompt": payload})
                            await client.query(payload)
                            continue
                    elif sig == "unlock":
                        session_gate.force_unlock()
                        await db.log_audit(run_id, "session_unlocked", {})

                # --- Reset to worker role after CEO round completes ---
                if hooks._agent_role == "ceo":
                    hooks.set_agent_role("worker")

                # --- Continue logic ---
                # Without a time lock or session unlocked: let the agent finish naturally
                if duration_minutes <= 0 or session_gate.is_unlocked():
                    if round_result and round_result.subtype == "success":
                        print("[agent] Round complete, no time lock — finishing")
                        final_status = "completed"
                        break
                    elif rate_limited:
                        await client.query(prompt.build_continuation_prompt())
                    else:
                        break
                else:
                    # =========================================================
                    # Time-locked: CEO/PM reviews work and assigns next task
                    # Flow: worker finishes → CEO decides → worker executes
                    # =========================================================

                    # --- Build round summary ---
                    tool_counts: dict[str, int] = {}
                    for t in round_tools:
                        tool_counts[t] = tool_counts.get(t, 0) + 1
                    tool_summary = ", ".join(f"{t} x{c}" for t, c in sorted(tool_counts.items(), key=lambda x: -x[1])[:10])

                    try:
                        files_changed = git_ops._run_git(["diff", "--name-only", "HEAD~5..HEAD"], cwd=work_dir)
                    except Exception:
                        files_changed = "(unable to determine)"
                    try:
                        commits = git_ops._run_git(["log", "--oneline", "-5"], cwd=work_dir)
                    except Exception:
                        commits = "(none yet)"

                    round_summary = "\n".join(round_text_chunks)[-1500:] if round_text_chunks else "Agent worked silently (tool calls only)."

                    ceo_prompt = prompt.build_ceo_continuation(
                        round_num=round_num + 1,
                        elapsed_minutes=session_gate.elapsed_minutes(),
                        duration_minutes=duration_minutes,
                        tool_summary=tool_summary,
                        files_changed=files_changed,
                        commits=commits,
                        cost_so_far=total_cost,
                        round_summary=round_summary,
                        original_prompt=custom_prompt or "General self-improvement pass on the SignalPilot codebase.",
                    )

                    await db.log_audit(run_id, "ceo_continuation", {
                        "round": round_num + 1,
                        "tool_summary": tool_summary,
                        "files_changed": files_changed[:500],
                        "round_summary": round_summary[:500],
                    })

                    # --- CEO round: send prompt, collect the CEO's decision ---
                    print(f"[agent] CEO reviewing round {round_num + 1}...")
                    hooks.set_agent_role("ceo")
                    await client.query(ceo_prompt)

                    ceo_decision_chunks: list[str] = []
                    async for msg in client.receive_response():
                        signal = await _drain_signal()
                        if signal and signal["signal"] == "stop":
                            final_status = "stopped"
                            should_stop = True
                            break

                        if isinstance(msg, StreamEvent):
                            event_data = msg.event or {}
                            if event_data.get("type") == "content_block_delta":
                                delta = event_data.get("delta", {})
                                dtype = delta.get("type", "")
                                if dtype == "text_delta" and delta.get("text"):
                                    try:
                                        await db.log_audit(run_id, "llm_text", {"text": delta["text"][:2000], "agent_role": "ceo"})
                                    except Exception:
                                        pass
                                elif dtype == "thinking_delta" and delta.get("thinking"):
                                    try:
                                        await db.log_audit(run_id, "llm_thinking", {"text": delta["thinking"][:2000], "agent_role": "ceo"})
                                    except Exception:
                                        pass
                            continue

                        if isinstance(msg, AssistantMessage):
                            for block in msg.content:
                                if isinstance(block, TextBlock):
                                    ceo_decision_chunks.append(block.text)
                                    print(f"[agent] [CEO] {block.text[:200].replace(chr(10), ' ')}")
                                elif isinstance(block, ThinkingBlock):
                                    print(f"[agent] [CEO thinking] {block.thinking[:100]}...")
                            if msg.usage:
                                total_input_tokens += msg.usage.get("input_tokens", 0)
                                total_output_tokens += msg.usage.get("output_tokens", 0)

                        elif isinstance(msg, ResultMessage):
                            if msg.total_cost_usd:
                                total_cost = msg.total_cost_usd

                    if should_stop:
                        break

                    # --- Hand CEO decision to worker ---
                    ceo_decision = "\n".join(ceo_decision_chunks).strip()
                    hooks.set_agent_role("worker")

                    if not ceo_decision:
                        ceo_decision = "Review and improve the quality of your previous work. Re-read what you wrote, refine it, and make it better."

                    worker_prompt = (
                        f"## Assignment from Product Director\n\n"
                        f"{ceo_decision}\n\n"
                        f"Complete this assignment, then stop. Do not do anything beyond what is described above."
                    )

                    await db.log_audit(run_id, "worker_assignment", {
                        "round": round_num + 2,
                        "assignment": ceo_decision[:1000],
                    })

                    print(f"[agent] Worker assigned round {round_num + 2} task")
                    await client.query(worker_prompt)

    except asyncio.CancelledError:
        print("[agent] Run KILLED by operator")
        final_status = "killed"
        await db.log_audit(run_id, "killed", {"elapsed_minutes": round(session_gate.elapsed_minutes(), 1)})
    except Exception as e:
        print(f"[agent] Fatal error: {e}")
        final_status = "error"
        await db.log_audit(run_id, "fatal_error", {"error": str(e)})
    finally:
        await _stop_signal_listener()

    # --- Post-run: push and create PR ---
    if final_status != "killed":
        try:
            current = git_ops.get_current_branch()
            if current == branch_name:
                git_ops.push_branch(branch_name)
                pr_url = git_ops.create_pr(branch_name, run_id)
                print(f"[agent] PR created: {pr_url}")
                await db.log_audit(run_id, "pr_created", {"url": pr_url, "branch": branch_name})
        except Exception as e:
            print(f"[agent] Failed to create PR: {e}")
            await db.log_audit(run_id, "pr_failed", {"error": str(e)})

    await db.finish_run(
        run_id=run_id,
        status=final_status,
        pr_url=pr_url,
        total_cost_usd=total_cost,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
    )

    _current_run_id = None
    print(f"[agent] Run complete. Status: {final_status}, Cost: ${total_cost:.2f}, Elapsed: {session_gate.elapsed_minutes():.0f}m")


# =============================================================================
# HTTP server
# =============================================================================

class StartRequest(BaseModel):
    prompt: str | None = None
    max_budget_usd: float = 0
    duration_minutes: float = 0
    base_branch: str = "main"


@asynccontextmanager
async def lifespan(app: FastAPI):
    dsn = os.environ["AUDIT_DB_URL"]
    await db.init_pool(dsn)
    crashed = await db.mark_crashed_runs()
    if crashed:
        print(f"[agent] Marked {crashed} stale run(s) as crashed from previous restart")
    print("[agent] Ready — waiting for start command on :8500")
    yield


app = FastAPI(title="Self-Improve Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "idle" if _current_run_id is None else "running",
        "current_run_id": _current_run_id,
        "elapsed_minutes": round(session_gate.elapsed_minutes(), 1) if _current_run_id else None,
        "time_remaining": session_gate.time_remaining_str() if _current_run_id else None,
        "session_unlocked": session_gate.is_unlocked() if _current_run_id else None,
    }


def _on_task_done(task: asyncio.Task) -> None:
    global _current_run_id
    try:
        exc = task.exception()
        if exc:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            print(f"[agent] Run task crashed:\n{tb}", flush=True)
    except asyncio.CancelledError:
        pass  # Expected from /kill
    _current_run_id = None


@app.post("/start")
async def start_run(body: StartRequest = StartRequest()):
    global _current_task
    if _current_run_id is not None:
        raise HTTPException(status_code=409, detail=f"Run already in progress: {_current_run_id}")

    budget = body.max_budget_usd if body.max_budget_usd is not None and body.max_budget_usd != 0 else float(os.environ.get("MAX_BUDGET_USD", "0"))
    _current_task = asyncio.create_task(
        run_agent(
            custom_prompt=body.prompt,
            max_budget=budget,
            duration_minutes=body.duration_minutes,
            base_branch=body.base_branch,
        )
    )
    _current_task.add_done_callback(_on_task_done)
    await asyncio.sleep(2)
    return {
        "ok": True,
        "run_id": _current_run_id,
        "prompt": body.prompt[:200] if body.prompt else None,
        "max_budget_usd": budget,
        "duration_minutes": body.duration_minutes,
        "base_branch": body.base_branch,
    }


@app.post("/stop")
async def stop_run_instant():
    """Push stop signal directly to the in-process queue. Instant delivery."""
    if _current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    _push_signal("stop", "Operator stop via API")
    return {"ok": True, "signal": "stop", "delivery": "instant"}


@app.post("/kill")
async def kill_run():
    """Immediately cancel the running task. No cleanup, no PR."""
    global _current_run_id
    if _current_task is None or _current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")

    run_id = _current_run_id
    _current_task.cancel()
    # Give it a moment to process the cancellation
    await asyncio.sleep(0.5)
    # Force update DB in case the task didn't get to clean up
    try:
        await db.finish_run(run_id=run_id, status="killed")
    except Exception:
        pass
    _current_run_id = None
    return {"ok": True, "signal": "kill", "run_id": run_id}


@app.get("/branches")
async def list_branches():
    try:
        git_ops.setup_git_auth()
        output = git_ops._run_git(["branch", "-r", "--format", "%(refname:short)"])
        branches = [b.replace("origin/", "") for b in output.strip().split("\n") if b.strip() and "HEAD" not in b]
        return sorted(set(branches))
    except Exception:
        return ["main", "staging"]


def main():
    uvicorn.run(app, host="0.0.0.0", port=8500, log_level="info")


if __name__ == "__main__":
    main()
