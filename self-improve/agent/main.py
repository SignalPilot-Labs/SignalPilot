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
from claude_agent_sdk.types import RateLimitEvent, StreamEvent, HookMatcher, AgentDefinition

from agent import db, hooks, git_ops, permissions, prompt, session_gate


# =============================================================================
# Helpers
# =============================================================================

def _is_workspace_same_repo(github_repo: str) -> bool:
    """Check if /workspace is the same repo as GITHUB_REPO.

    This determines whether bundled skills should be copied into the
    cloned repo. If someone sets a different GITHUB_REPO, the bundled
    SignalPilot-specific skills should NOT be copied.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd="/workspace",
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return False
        origin = result.stdout.strip().lower()
        # Normalize: extract owner/repo from the URL
        # Handle https://github.com/owner/repo.git and git@github.com:owner/repo.git
        for prefix in ["https://github.com/", "git@github.com:"]:
            if prefix in origin:
                slug = origin.split(prefix)[-1].rstrip(".git").strip("/")
                return slug == github_repo.lower()
        return github_repo.lower() in origin
    except Exception:
        return False


# =============================================================================
# Shared state
# =============================================================================
_current_run_id: str | None = None
_current_task: asyncio.Task | None = None
_signal_queue: asyncio.Queue | None = None  # Instant control signal delivery
_audit_log_warned: bool = False  # Log audit failures once, then suppress


# =============================================================================
# Instant signal delivery via HTTP endpoints + in-process queue
# =============================================================================

def _init_signal_queue() -> None:
    """Initialize the signal queue for a new run."""
    global _signal_queue
    _signal_queue = asyncio.Queue()
    print("[agent] Signal queue initialized")


def _teardown_signal_queue() -> None:
    """Tear down the signal queue."""
    global _signal_queue
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
    global _current_run_id, _audit_log_warned
    _audit_log_warned = False

    model = os.environ.get("AGENT_MODEL", "opus")
    fallback_model = os.environ.get("AGENT_FALLBACK_MODEL", "sonnet")

    # --- Git setup ---
    git_ops.setup_git_auth()
    git_ops.ensure_base_branch(base_branch)
    branch_name = git_ops.get_branch_name()
    git_ops.create_branch(branch_name, base_branch=base_branch)
    print(f"[agent] Created branch: {branch_name} (from {base_branch})")

    # --- DB record ---
    run_id = await db.create_run(
        branch_name,
        custom_prompt=custom_prompt,
        duration_minutes=duration_minutes,
        base_branch=base_branch,
    )
    _current_run_id = run_id
    print(f"[agent] Run ID: {run_id}")

    hooks.set_run_id(run_id)
    hooks.set_agent_role("worker")
    permissions.set_run_id(run_id)
    session_gate.configure(run_id, duration_minutes)
    session_mcp = session_gate.create_session_mcp_server()

    # --- Start instant signal queue ---
    _init_signal_queue()

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

    # --- Copy skills into cloned repo (only if they belong to this repo) ---
    work_dir = git_ops.get_work_dir()
    skills_src = Path("/workspace/self-improve/.claude")
    skills_dst = Path(work_dir) / ".claude"
    # Only copy the bundled skills if /workspace is the same repo we're targeting
    # (i.e., the self-improve framework is inside the target repo). Otherwise,
    # the cloned repo should use its own .claude config if present.
    workspace_repo = os.environ.get("GITHUB_REPO", "")
    workspace_is_target = (
        skills_src.exists()
        and workspace_repo
        and _is_workspace_same_repo(workspace_repo)
    )
    if workspace_is_target:
        if skills_dst.exists():
            shutil.rmtree(skills_dst)
        shutil.copytree(skills_src, skills_dst)
        print(f"[agent] Copied skills to {skills_dst}")
    else:
        print(f"[agent] Skipping skill copy — target repo differs from workspace")

    # --- Subagents for parallel work (prompts loaded from prompts/agent-*.md) ---
    subagents = {
        "code-writer": AgentDefinition(
            description="Use for writing new files, generating boilerplate, creating components, or implementing straightforward features. Delegates code generation so the main agent can continue planning.",
            prompt=prompt.load_agent_prompt("code-writer"),
            model="sonnet",
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        "test-writer": AgentDefinition(
            description="Use for writing tests, running test suites, and verifying code works correctly. Delegates test creation and execution.",
            prompt=prompt.load_agent_prompt("test-writer"),
            model="sonnet",
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        "researcher": AgentDefinition(
            description="Use for researching the codebase, finding patterns, understanding architecture, or looking up documentation. Returns findings without making changes.",
            prompt=prompt.load_agent_prompt("researcher"),
            model="sonnet",
            tools=["Read", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"],
        ),
        "frontend-builder": AgentDefinition(
            description="Use for building React/Next.js components, pages, layouts, and styling. Handles TSX, CSS, Tailwind, and frontend-specific code generation.",
            prompt=prompt.load_agent_prompt("frontend-builder"),
            model="sonnet",
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        ),
        "reviewer": AgentDefinition(
            description="MUST be called after completing each feature or significant change. Reviews recent commits for security vulnerabilities, performance issues, duplicated code, god files, and code quality problems. Runs on Opus for thorough analysis. Returns a structured review with critical issues, warnings, and files that need splitting.",
            prompt=prompt.load_agent_prompt("reviewer"),
            model="opus",
            tools=["Read", "Glob", "Grep", "Bash"],
        ),
    }

    # --- SDK options ---
    options = ClaudeAgentOptions(
        model=model,
        fallback_model=fallback_model if fallback_model != model else None,
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
        mcp_servers={"session_gate": session_mcp},
        agents=subagents,
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
                _pending_inject: str | None = None

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
                            # Queue for delivery after current round completes
                            _pending_inject = signal.get("payload", "")
                            await db.log_audit(run_id, "prompt_injected", {"prompt": _pending_inject, "delivery": "queued"})

                    # --- StreamEvent ---
                    if isinstance(message, StreamEvent):
                        event_data = message.event or {}
                        if event_data.get("type") == "content_block_delta":
                            delta = event_data.get("delta", {})
                            dtype = delta.get("type", "")
                            if dtype == "text_delta" and delta.get("text"):
                                try:
                                    await db.log_audit(run_id, "llm_text", {"text": delta["text"][:2000], "agent_role": hooks._agent_role})
                                except Exception as _audit_err:
                                    if not _audit_log_warned:
                                        print(f"[agent] Warning: audit logging failed (suppressing further): {_audit_err}")
                                        _audit_log_warned = True
                            elif dtype == "thinking_delta" and delta.get("thinking"):
                                try:
                                    await db.log_audit(run_id, "llm_thinking", {"text": delta["thinking"][:2000], "agent_role": hooks._agent_role})
                                except Exception as _audit_err:
                                    if not _audit_log_warned:
                                        print(f"[agent] Warning: audit logging failed (suppressing further): {_audit_err}")
                                        _audit_log_warned = True
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
                            except Exception as _audit_err:
                                if not _audit_log_warned:
                                    print(f"[agent] Warning: audit logging failed (suppressing further): {_audit_err}")
                                    _audit_log_warned = True

                    # --- RateLimitEvent ---
                    elif isinstance(message, RateLimitEvent):
                        info = message.rate_limit_info
                        await db.log_audit(run_id, "rate_limit", {
                            "status": info.status,
                            "resets_at": info.resets_at,
                            "utilization": info.utilization,
                        })
                        if info.status == "rejected":
                            resets_at = info.resets_at
                            wait_sec = max(0, resets_at - time.time()) if resets_at else 0

                            if fallback_model and fallback_model != model:
                                # Fallback model is configured — the SDK should auto-retry
                                # with the fallback. Log it and let the loop continue.
                                print(f"[agent] Rate limited on {model}, SDK should fallback to {fallback_model}. Continuing...")
                                await db.log_audit(run_id, "rate_limit_fallback", {
                                    "primary_model": model,
                                    "fallback_model": fallback_model,
                                    "resets_at": resets_at,
                                })
                                # Don't break — let the SDK handle the retry
                            else:
                                # No fallback — save state and exit for manual resume
                                wait_min = int(wait_sec / 60)
                                print(f"[agent] Rate limited. Resets in {wait_min}m. Pausing run for resume.")
                                await db.update_run_status(run_id, "rate_limited")
                                if resets_at:
                                    await db.save_rate_limit_reset(run_id, int(resets_at))
                                await db.log_audit(run_id, "rate_limit_paused", {
                                    "resets_at": resets_at,
                                    "wait_seconds": int(wait_sec) if resets_at else None,
                                    "message": "Run paused. Use Resume to continue when rate limit clears.",
                                })
                                final_status = "rate_limited"
                                should_stop = True
                                break

                    # --- ResultMessage ---
                    elif isinstance(message, ResultMessage):
                        round_result = message
                        # Save session ID on first result (available immediately)
                        if message.session_id:
                            try:
                                await db.save_session_id(run_id, message.session_id)
                            except Exception as e:
                                print(f"[agent] Warning: failed to save session ID: {e}")
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
                        _pending_inject = signal.get("payload", "")
                        await db.log_audit(run_id, "prompt_injected", {"prompt": _pending_inject, "delivery": "queued"})
                    elif sig == "unlock":
                        session_gate.force_unlock()
                        await db.log_audit(run_id, "session_unlocked", {})

                # --- Reset to worker role after CEO round completes ---
                if hooks._agent_role == "ceo":
                    hooks.set_agent_role("worker")

                # --- Push commits between rounds so work isn't lost ---
                try:
                    git_ops.push_branch(branch_name)
                    print(f"[agent] Pushed branch {branch_name}")
                except Exception as e:
                    print(f"[agent] Push between rounds failed (non-fatal): {e}")

                # --- Continue logic ---
                # Without a time lock or session unlocked: let the agent finish naturally
                if duration_minutes <= 0 or session_gate.is_unlocked():
                    # If operator injected a message, deliver it as a continuation
                    if _pending_inject:
                        await db.log_audit(run_id, "prompt_injected", {"prompt": _pending_inject})
                        await client.query(f"Operator message: {_pending_inject}")
                        _pending_inject = None
                        continue
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

                    # Include any pending injected message from the operator
                    if _pending_inject:
                        ceo_prompt += (
                            f"\n\n---\n\n## Operator Message\n"
                            f"The operator injected this message during the last round. "
                            f"Factor it into your next assignment:\n\n> {_pending_inject}"
                        )
                        await db.log_audit(run_id, "prompt_injected", {"prompt": _pending_inject, "delivery": "with_ceo"})
                        _pending_inject = None

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
                                    except Exception as _audit_err:
                                        if not _audit_log_warned:
                                            print(f"[agent] Warning: audit logging failed (suppressing further): {_audit_err}")
                                            _audit_log_warned = True
                                elif dtype == "thinking_delta" and delta.get("thinking"):
                                    try:
                                        await db.log_audit(run_id, "llm_thinking", {"text": delta["thinking"][:2000], "agent_role": "ceo"})
                                    except Exception as _audit_err:
                                        if not _audit_log_warned:
                                            print(f"[agent] Warning: audit logging failed (suppressing further): {_audit_err}")
                                            _audit_log_warned = True
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
        _teardown_signal_queue()

    # --- Post-run: push and create PR ---
    if final_status != "killed":
        try:
            current = git_ops.get_current_branch()
            if current == branch_name:
                git_ops.push_branch(branch_name)
                pr_url = git_ops.create_pr(branch_name, run_id, base_branch=base_branch)
                print(f"[agent] PR created: {pr_url}")
                await db.log_audit(run_id, "pr_created", {"url": pr_url, "branch": branch_name})
        except Exception as e:
            print(f"[agent] Failed to create PR: {e}")
            await db.log_audit(run_id, "pr_failed", {"error": str(e)})

    # Capture git diff stats before finishing
    diff_stats = None
    try:
        diff_stats = git_ops.get_branch_diff(branch_name, base_branch)
        print(f"[agent] Captured diff: {len(diff_stats)} files changed")
    except Exception as e:
        print(f"[agent] Warning: could not capture diff stats: {e}")

    await db.finish_run(
        run_id=run_id,
        status=final_status,
        pr_url=pr_url,
        total_cost_usd=total_cost,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        diff_stats=diff_stats,
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
    # Credentials passed by monitor (decrypted from settings DB)
    claude_token: str | None = None
    git_token: str | None = None
    github_repo: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("DB_PATH", "/data/improve.db")
    await db.init_db(db_path)
    crashed = await db.mark_crashed_runs()
    if crashed:
        print(f"[agent] Marked {crashed} stale run(s) as crashed from previous restart")
    print("[agent] Ready — waiting for start command on :8500")
    yield
    try:
        await db.close_db()
    except Exception as e:
        print(f"[agent] Warning: error closing database: {e}")


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

    # Inject credentials from monitor (takes priority over env vars)
    if body.claude_token:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = body.claude_token
    if body.git_token:
        os.environ["GIT_TOKEN"] = body.git_token
    if body.github_repo:
        os.environ["GITHUB_REPO"] = body.github_repo

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


class ResumeRequest(BaseModel):
    run_id: str
    max_budget_usd: float = 0
    claude_token: str | None = None
    git_token: str | None = None
    github_repo: str | None = None


async def resume_agent(run_id: str, max_budget: float = 0):
    """Resume a previous run using its SDK session ID."""
    global _current_run_id, _audit_log_warned
    _audit_log_warned = False

    run_info = await db.get_run_for_resume(run_id)
    if not run_info:
        raise RuntimeError(f"Run {run_id} not found")
    session_id = run_info.get("sdk_session_id")  # May be None — will start fresh

    branch_name = run_info["branch_name"]
    custom_prompt = run_info.get("custom_prompt")
    duration_minutes = run_info.get("duration_minutes", 0)
    base_branch = run_info.get("base_branch", "main")
    model = os.environ.get("AGENT_MODEL", "opus")
    fallback_model = os.environ.get("AGENT_FALLBACK_MODEL", "sonnet")

    # --- Git setup: checkout the existing branch ---
    git_ops.setup_git_auth()
    work_dir = git_ops.get_work_dir()
    try:
        git_ops._run_git(["fetch", "origin", branch_name], cwd=work_dir)
        git_ops._run_git(["checkout", branch_name], cwd=work_dir)
        git_ops._run_git(["pull", "origin", branch_name], cwd=work_dir)
        print(f"[agent] Resumed on branch: {branch_name}")
    except Exception as e:
        print(f"[agent] Warning: couldn't checkout branch {branch_name}: {e}")
        # Branch might only be local, try just checkout
        try:
            git_ops._run_git(["checkout", branch_name], cwd=work_dir)
        except Exception:
            print(f"[agent] Branch {branch_name} not found — starting fresh from {base_branch}")
            git_ops.create_branch(branch_name, base_branch=base_branch)

    _current_run_id = run_id
    hooks.set_run_id(run_id)
    hooks.set_agent_role("worker")
    permissions.set_run_id(run_id)
    session_gate.configure(run_id, duration_minutes)
    session_mcp = session_gate.create_session_mcp_server()

    _init_signal_queue()
    await db.update_run_status(run_id, "running")
    await db.log_audit(run_id, "session_resumed", {
        "sdk_session_id": session_id[:20] if session_id else None,
        "branch": branch_name,
    })

    # --- Copy skills (only if workspace matches target repo) ---
    skills_src = Path("/workspace/self-improve/.claude")
    skills_dst = Path(work_dir) / ".claude"
    repo = os.environ.get("GITHUB_REPO", "")
    if skills_src.exists() and repo and _is_workspace_same_repo(repo):
        if skills_dst.exists():
            shutil.rmtree(skills_dst)
        shutil.copytree(skills_src, skills_dst)

    # --- SDK options with resume ---
    options = ClaudeAgentOptions(
        model=model,
        fallback_model=fallback_model if fallback_model != model else None,
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
        resume=session_id if session_id else None,
        mcp_servers={"session_gate": session_mcp},
        hooks={
            "PreToolUse": [HookMatcher(hooks=[hooks.pre_tool_use_hook])],
            "PostToolUse": [HookMatcher(hooks=[hooks.post_tool_use_hook])],
            "Stop": [HookMatcher(hooks=[hooks.stop_hook])],
        },
    )

    if session_id:
        print(f"[agent] Resuming session {session_id[:12]}...")
    else:
        print(f"[agent] No session ID — starting fresh on branch {branch_name}")

    total_cost = run_info.get("total_cost_usd", 0) or 0
    total_input_tokens = run_info.get("total_input_tokens", 0) or 0
    total_output_tokens = run_info.get("total_output_tokens", 0) or 0
    final_status = "completed"

    try:
        async with ClaudeSDKClient(options=options) as client:
            # Send a continuation prompt to pick up where we left off
            await client.query(
                "You are resuming a previous session. Continue where you left off. "
                "Check your recent commits with `git log --oneline -5` to remember what you were working on."
            )
            print("[agent] Resume prompt sent")

            # Re-enter the main loop (simplified — same structure as run_agent)
            for round_num in range(500):
                current_role = hooks._agent_role
                print(f"[agent] Round {round_num + 1} [{current_role.upper()}] | Resumed | Elapsed: {session_gate.elapsed_minutes():.0f}m")

                round_result = None
                should_stop = False
                round_tools: list[str] = []
                round_text_chunks: list[str] = []

                async for message in client.receive_response():
                    signal = await _drain_signal()
                    if signal:
                        sig = signal["signal"]
                        if sig == "stop":
                            await client.interrupt()
                            final_status = "stopped"
                            should_stop = True
                            break
                        elif sig == "unlock":
                            session_gate.force_unlock()
                            await db.log_audit(run_id, "session_unlocked", {})

                    if isinstance(message, StreamEvent):
                        event_data = message.event or {}
                        if event_data.get("type") == "content_block_delta":
                            delta = event_data.get("delta", {})
                            dtype = delta.get("type", "")
                            if dtype == "text_delta" and delta.get("text"):
                                try:
                                    await db.log_audit(run_id, "llm_text", {"text": delta["text"][:2000], "agent_role": hooks._agent_role})
                                except Exception as _audit_err:
                                    if not _audit_log_warned:
                                        print(f"[agent] Warning: audit logging failed (suppressing further): {_audit_err}")
                                        _audit_log_warned = True
                            elif dtype == "thinking_delta" and delta.get("thinking"):
                                try:
                                    await db.log_audit(run_id, "llm_thinking", {"text": delta["thinking"][:2000], "agent_role": hooks._agent_role})
                                except Exception as _audit_err:
                                    if not _audit_log_warned:
                                        print(f"[agent] Warning: audit logging failed (suppressing further): {_audit_err}")
                                        _audit_log_warned = True
                        continue

                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                round_text_chunks.append(block.text[:500])
                            elif isinstance(block, ToolUseBlock):
                                round_tools.append(block.name)
                        if message.usage:
                            total_input_tokens += message.usage.get("input_tokens", 0)
                            total_output_tokens += message.usage.get("output_tokens", 0)

                    elif isinstance(message, ResultMessage):
                        round_result = message
                        if message.total_cost_usd:
                            total_cost = message.total_cost_usd

                if should_stop:
                    break

                if session_gate.has_ended():
                    final_status = "completed"
                    break

                if hooks._agent_role == "ceo":
                    hooks.set_agent_role("worker")

                # Same continue logic as run_agent
                if duration_minutes <= 0 or session_gate.is_unlocked():
                    if round_result and round_result.subtype == "success":
                        final_status = "completed"
                        break
                    else:
                        break
                else:
                    # CEO continuation (same as run_agent)
                    await client.query(prompt.build_continuation_prompt())

    except asyncio.CancelledError:
        final_status = "killed"
    except Exception as e:
        print(f"[agent] Resume error: {e}")
        final_status = "error"
        await db.log_audit(run_id, "fatal_error", {"error": str(e)})
    finally:
        _teardown_signal_queue()

    if final_status != "killed":
        try:
            current = git_ops.get_current_branch()
            if current == branch_name:
                git_ops.push_branch(branch_name)
                pr_url = git_ops.create_pr(branch_name, run_id, base_branch=base_branch)
                await db.log_audit(run_id, "pr_created", {"url": pr_url})
        except Exception as e:
            print(f"[agent] PR failed: {e}")

    # Capture git diff stats
    diff_stats = None
    try:
        diff_stats = git_ops.get_branch_diff(branch_name, base_branch)
    except Exception as e:
        print(f"[agent] Warning: could not capture diff stats: {e}")

    await db.finish_run(
        run_id=run_id,
        status=final_status,
        total_cost_usd=total_cost,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        diff_stats=diff_stats,
    )
    _current_run_id = None
    print(f"[agent] Resume complete. Status: {final_status}")


@app.post("/resume")
async def resume_run(body: ResumeRequest):
    global _current_task
    if _current_run_id is not None:
        raise HTTPException(status_code=409, detail=f"Run already in progress: {_current_run_id}")

    # Inject credentials from monitor
    if body.claude_token:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = body.claude_token
    if body.git_token:
        os.environ["GIT_TOKEN"] = body.git_token
    if body.github_repo:
        os.environ["GITHUB_REPO"] = body.github_repo

    budget = body.max_budget_usd or float(os.environ.get("MAX_BUDGET_USD", "0"))
    _current_task = asyncio.create_task(resume_agent(body.run_id, budget))
    _current_task.add_done_callback(_on_task_done)
    await asyncio.sleep(2)
    return {"ok": True, "run_id": body.run_id, "resumed": True}


class InjectRequest(BaseModel):
    payload: str | None = None


@app.post("/pause")
async def pause_agent():
    """Push pause signal to the in-process queue."""
    if _current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    _push_signal("pause")
    return {"ok": True, "signal": "pause", "delivery": "instant"}


@app.post("/resume_signal")
async def resume_agent_signal():
    """Push resume signal to the in-process queue."""
    if _current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    _push_signal("resume")
    return {"ok": True, "signal": "resume", "delivery": "instant"}


@app.post("/inject")
async def inject_agent(body: InjectRequest = InjectRequest()):
    """Push inject signal with payload to the in-process queue."""
    if _current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    _push_signal("inject", body.payload)
    return {"ok": True, "signal": "inject", "delivery": "instant"}


@app.post("/unlock")
async def unlock_agent():
    """Push unlock signal to the in-process queue."""
    if _current_run_id is None:
        raise HTTPException(status_code=409, detail="No run in progress")
    _push_signal("unlock")
    return {"ok": True, "signal": "unlock", "delivery": "instant"}


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
    except Exception as e:
        print(f"[agent] Warning: failed to mark run as killed in DB: {e}")
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
        return ["main"]


@app.get("/diff/live")
async def get_live_diff():
    """Get diff stats for the currently running branch (including uncommitted)."""
    try:
        git_ops.setup_git_auth()
        # Determine base branch from current run
        base = "main"
        if _current_run_id:
            conn = db.get_db()
            cursor = await conn.execute("SELECT base_branch FROM runs WHERE id = ?", (_current_run_id,))
            row = await cursor.fetchone()
            if row and row["base_branch"]:
                base = row["base_branch"]
        stats = git_ops.get_branch_diff_live(base)
        return {"files": stats, "total_files": len(stats),
                "total_added": sum(f["added"] for f in stats),
                "total_removed": sum(f["removed"] for f in stats)}
    except Exception as e:
        return {"files": [], "error": str(e)}


@app.get("/diff/{branch}")
async def get_branch_diff(branch: str, base: str = "main"):
    """Get diff stats between a branch and its base."""
    try:
        git_ops.setup_git_auth()
        stats = git_ops.get_branch_diff(branch, base)
        return {"files": stats, "total_files": len(stats),
                "total_added": sum(f["added"] for f in stats),
                "total_removed": sum(f["removed"] for f in stats)}
    except Exception as e:
        return {"files": [], "error": str(e)}


def main():
    uvicorn.run(app, host="0.0.0.0", port=8500, log_level="info")


if __name__ == "__main__":
    main()
