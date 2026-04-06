"""Agent run execution — run_agent and resume_agent.

Contains the main agent loop, CEO/Worker continuation, and all run
lifecycle logic. Signal handling is delegated to signals.py.
"""

import asyncio
import json as _json
import os
import shutil
import time
from pathlib import Path

from agent.key_pool import KeyPool

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import RateLimitEvent, StreamEvent, HookMatcher

from agent import db, hooks, git_ops, permissions, prompt, session_gate, signals, subagents


# =============================================================================
# Helpers
# =============================================================================

async def _log_stream_delta(run_id: str, event_data: dict, agent_role: str) -> None:
    """Log text/thinking deltas from a StreamEvent to the audit DB."""
    if event_data.get("type") != "content_block_delta":
        return
    delta = event_data.get("delta", {})
    dtype = delta.get("type", "")
    if dtype == "text_delta" and delta.get("text"):
        try:
            await db.log_audit(run_id, "llm_text", {"text": delta["text"], "agent_role": agent_role})
        except Exception as e:
            print(f"[agent] Audit log failed (text): {e}")
    elif dtype == "thinking_delta" and delta.get("thinking"):
        try:
            await db.log_audit(run_id, "llm_thinking", {"text": delta["thinking"], "agent_role": agent_role})
        except Exception as e:
            print(f"[agent] Audit log failed (thinking): {e}")


def _is_workspace_same_repo(github_repo: str) -> bool:
    """Check if /workspace is the same repo as GITHUB_REPO."""
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
        for prefix in ["https://github.com/", "git@github.com:"]:
            if prefix in origin:
                slug = origin.split(prefix)[-1].rstrip(".git").strip("/")
                return slug == github_repo.lower()
        return github_repo.lower() in origin
    except Exception:
        return False


def _copy_skills(work_dir: str) -> None:
    """Copy bundled skills into the cloned repo if it's the same repo."""
    skills_src = Path("/workspace/self-improve/.claude")
    skills_dst = Path(work_dir) / ".claude"
    repo = os.environ.get("GITHUB_REPO", "")
    if skills_src.exists() and repo and _is_workspace_same_repo(repo):
        if skills_dst.exists():
            shutil.rmtree(skills_dst)
        shutil.copytree(skills_src, skills_dst)
        print(f"[agent] Copied skills to {skills_dst}")
    else:
        print(f"[agent] Skipping skill copy — target repo differs from workspace")


def _build_sdk_options(
    model: str,
    fallback_model: str | None,
    work_dir: str,
    custom_prompt: str | None,
    duration_minutes: float,
    max_budget: float,
    session_mcp,
    agent_defs: dict,
    resume_session_id: str | None = None,
) -> ClaudeAgentOptions:
    """Build SDK options common to both run and resume."""
    return ClaudeAgentOptions(
        model=model,
        fallback_model=fallback_model if fallback_model and fallback_model != model else None,
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
        resume=resume_session_id,
        mcp_servers={"session_gate": session_mcp},
        agents=agent_defs,
        hooks={
            "PreToolUse": [HookMatcher(hooks=[hooks.pre_tool_use_hook])],
            "PostToolUse": [HookMatcher(hooks=[hooks.post_tool_use_hook])],
            "Stop": [HookMatcher(hooks=[hooks.stop_hook])],
            "SubagentStart": [HookMatcher(hooks=[hooks.subagent_start_hook])],
            "SubagentStop": [HookMatcher(hooks=[hooks.subagent_stop_hook])],
        },
    )


# =============================================================================
# Shared main loop
# =============================================================================

async def _run_loop(
    client: ClaudeSDKClient,
    run_id: str,
    branch_name: str,
    custom_prompt: str | None,
    duration_minutes: float,
    model: str,
    fallback_model: str | None,
    base_branch: str,
    initial_cost: float = 0,
    initial_input_tokens: int = 0,
    initial_output_tokens: int = 0,
    key_pool: KeyPool | None = None,
) -> tuple[str, float, int, int, bool]:
    """Shared loop for both run_agent and resume_agent.

    Returns (final_status, total_cost, total_input_tokens, total_output_tokens, should_restart_client).
    """
    total_cost = initial_cost
    total_input_tokens = initial_input_tokens
    total_output_tokens = initial_output_tokens
    final_status = "completed"
    max_rounds = 500
    work_dir = git_ops.get_work_dir()

    for round_num in range(max_rounds):
        current_role = hooks._agent_role
        print(f"[agent] Round {round_num + 1} [{current_role.upper()}] | Elapsed: {session_gate.elapsed_minutes():.0f}m | Remaining: {session_gate.time_remaining_str()}")

        round_result = None
        should_stop = False

        # --- Per-round tracking for CEO summary ---
        round_tools: list[str] = []
        round_text_chunks: list[str] = []
        _pending_inject: str | None = None

        async for message in client.receive_response():
            # --- Instant signal check (non-blocking) ---
            signal = await signals.drain_signal()
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
                    result = await signals.handle_pause(run_id)
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
                    _pending_inject = signal.get("payload", "")
                    await db.log_audit(run_id, "prompt_injected", {"prompt": _pending_inject, "delivery": "queued"})
                elif sig == "stuck_recovery":
                    stuck_info = signal.get("payload", "[]")
                    print(f"[agent] STUCK RECOVERY: interrupting for stuck subagents")
                    await client.interrupt()
                    async for _ in client.receive_response():
                        pass
                    recovery_prompt = (
                        "IMPORTANT: One or more subagents got stuck and had to be killed. "
                        f"Stuck agent details: {stuck_info}\n\n"
                        "Please manually achieve what those subagents were supposed to do, "
                        "or break the task into smaller, simpler parts. "
                        "Do NOT re-spawn the same agent with the same task — instead, "
                        "do the work directly or split it into multiple smaller agent calls."
                    )
                    await db.log_audit(run_id, "stuck_recovery", {"stuck_info": stuck_info, "recovery_prompt": recovery_prompt})
                    await client.query(recovery_prompt)
                    signals.start_pulse_checker(run_id)
                    break

            # --- StreamEvent ---
            if isinstance(message, StreamEvent):
                await _log_stream_delta(run_id, message.event or {}, hooks._agent_role)
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
                    except Exception as e:
                        print(f"[agent] Failed to log token usage: {e}")

            # --- RateLimitEvent ---
            elif isinstance(message, RateLimitEvent):
                info = message.rate_limit_info
                await db.log_audit(run_id, "rate_limit", {
                    "status": info.status,
                    "resets_at": info.resets_at,
                    "utilization": info.utilization,
                    "active_key_id": key_pool.active_key_id if key_pool else None,
                })
                if info.status == "rejected":
                    if key_pool:
                        # Try to rotate to next available key (marks current key internally)
                        next_key = await key_pool.handle_rate_limit(
                            resets_at=info.resets_at,
                            utilization=info.utilization,
                        )
                        if next_key is not None:
                            if next_key.provider == "codex":
                                # Codex degraded mode — wait for Claude keys to reset
                                # while keeping the run alive
                                print(f"[agent] Codex fallback activated (degraded mode)")
                                await db.log_audit(run_id, "codex_degraded_mode", {
                                    "codex_key_id": next_key.id,
                                    "codex_model": "codex-mini-latest",
                                })
                                await db.update_run_status(run_id, "waiting_for_key")

                                # Poll for Claude key availability in 10s chunks
                                config = await key_pool.get_config()
                                max_wait = int(config.get("max_wait_minutes", "60")) * 60
                                waited = 0
                                claude_key = None
                                signal_break = False
                                while waited < max_wait:
                                    # Check signals before sleeping
                                    if signals.has_pending_signals():
                                        signal_break = True
                                        break

                                    # Try to get a Claude key
                                    claude_key = await key_pool.get_next_key(provider="claude_code")
                                    if claude_key:
                                        break

                                    # Sleep in 10s chunks for responsive signal handling
                                    sleep_target = min(60, max_wait - waited)
                                    slept = 0
                                    while slept < sleep_target:
                                        sleep_chunk = min(10, sleep_target - slept)
                                        await asyncio.sleep(sleep_chunk)
                                        slept += sleep_chunk
                                        if signals.has_pending_signals():
                                            signal_break = True
                                            break
                                    if signal_break:
                                        break
                                    waited += slept

                                if signal_break:
                                    await db.log_audit(run_id, "codex_fallback_ended", {
                                        "codex_key_id": next_key.id,
                                        "reason": "signal_received",
                                        "waited_seconds": waited,
                                    })
                                    # Fall through — signal will be handled by main loop
                                elif claude_key:
                                    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = claude_key.decrypted_value
                                    await db.log_audit(run_id, "codex_fallback_ended", {
                                        "codex_key_id": next_key.id,
                                        "claude_key_id": claude_key.id,
                                        "reason": "claude_key_available",
                                        "waited_seconds": waited,
                                    })
                                    await db.update_run_status(run_id, "running")
                                    print(f"[agent] Claude key available, leaving Codex mode: {claude_key.label or claude_key.id[:8]}")
                                    return final_status, total_cost, total_input_tokens, total_output_tokens, True
                                # Fall through to existing wait/pause logic below
                            else:
                                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = next_key.decrypted_value
                                print(f"[agent] Key rotated to {next_key.label or next_key.id[:8]}")
                                return final_status, total_cost, total_input_tokens, total_output_tokens, True
                        else:
                            # All keys exhausted — try auto-wait
                            next_key = await key_pool.wait_for_next_available_key(
                                should_stop_fn=signals.has_pending_signals,
                            )
                            if next_key is not None:
                                os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = next_key.decrypted_value
                                print(f"[agent] Key available after wait: {next_key.label or next_key.id[:8]}")
                                return final_status, total_cost, total_input_tokens, total_output_tokens, True
                            # Auto-wait exhausted or disabled
                            resets_at = info.resets_at
                            wait_min = int(max(0, (resets_at or 0) - time.time()) / 60)
                            await db.log_audit(run_id, "key_pool_exhausted", {
                                "earliest_reset": int(resets_at) if resets_at else None,
                                "wait_minutes": wait_min,
                                "active_key_id": key_pool.active_key_id,
                            })
                            print(f"[agent] All keys exhausted. Earliest reset in {wait_min}m. Pausing.")
                            await db.update_run_status(run_id, "rate_limited")
                            if resets_at:
                                await db.save_rate_limit_reset(run_id, int(resets_at))
                            final_status = "rate_limited"
                            should_stop = True
                            break
                    else:
                        # No key pool — legacy single-key behavior
                        resets_at = info.resets_at
                        wait_sec = max(0, resets_at - time.time()) if resets_at else 0
                        if fallback_model and fallback_model != model:
                            print(f"[agent] Rate limited on {model}, SDK should fallback to {fallback_model}. Continuing...")
                            await db.log_audit(run_id, "rate_limit_fallback", {
                                "primary_model": model,
                                "fallback_model": fallback_model,
                                "resets_at": resets_at,
                            })
                        else:
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
                if message.session_id:
                    try:
                        await db.save_session_id(run_id, message.session_id)
                    except Exception as e:
                        print(f"[agent] Failed to save session ID: {e}")
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
        signal = await signals.drain_signal()
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
                result = await signals.handle_pause(run_id)
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
            elif sig == "stuck_recovery":
                # Stuck recovery between rounds — just log and restart pulse checker.
                # The stuck subagent already exited; no need to interrupt the main agent.
                stuck_info = signal.get("payload", "[]")
                print(f"[agent] STUCK RECOVERY (between rounds): {stuck_info}")
                await db.log_audit(run_id, "stuck_recovery_between_rounds", {"stuck_info": stuck_info})
                signals.start_pulse_checker(run_id)

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
        if duration_minutes <= 0 or session_gate.is_unlocked():
            if _pending_inject:
                await db.log_audit(run_id, "prompt_injected", {"prompt": _pending_inject})
                await client.query(f"Operator message: {_pending_inject}")
                _pending_inject = None
                continue
            if round_result and round_result.subtype == "success":
                print("[agent] Round complete, no time lock — finishing")
                final_status = "completed"
                break
            else:
                break
        else:
            # =============================================================
            # Time-locked: CEO/PM reviews work and assigns next task
            # =============================================================

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
                signal = await signals.drain_signal()
                if signal and signal["signal"] == "stop":
                    final_status = "stopped"
                    should_stop = True
                    break

                if isinstance(msg, StreamEvent):
                    await _log_stream_delta(run_id, msg.event or {}, "ceo")
                    continue

                if isinstance(msg, RateLimitEvent):
                    info = msg.rate_limit_info
                    await db.log_audit(run_id, "rate_limit", {
                        "status": info.status, "resets_at": info.resets_at,
                        "context": "ceo_round",
                    })
                    if info.status == "rejected":
                        print(f"[agent] Rate limited during CEO round, waiting for reset...")
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

    return final_status, total_cost, total_input_tokens, total_output_tokens, False


# =============================================================================
# Post-run cleanup (shared between run and resume)
# =============================================================================

async def _post_run(
    run_id: str,
    branch_name: str,
    base_branch: str,
    final_status: str,
    total_cost: float,
    total_input_tokens: int,
    total_output_tokens: int,
) -> None:
    """Push final commits, create PR, and update DB."""
    pr_url = None

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

    # Capture git diff stats
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


# =============================================================================
# run_agent — start a new improvement run
# =============================================================================

async def run_agent(
    custom_prompt: str | None = None,
    max_budget: float = 50.0,
    duration_minutes: float = 0,
    base_branch: str = "main",
):
    """Execute one improvement run."""
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
    signals.current_run_id = run_id
    print(f"[agent] Run ID: {run_id}")

    hooks.set_run_id(run_id)
    hooks.set_agent_role("worker")
    permissions.set_run_id(run_id)
    session_gate.configure(run_id, duration_minutes)
    session_mcp = session_gate.create_session_mcp_server()

    # --- Start instant signal queue ---
    signals.init_signal_queue()
    signals.start_pulse_checker(run_id)

    duration_str = f"{duration_minutes}m" if duration_minutes > 0 else "unlimited"
    print(f"[agent] Duration: {duration_str}")

    await db.log_audit(run_id, "run_started", {
        "branch": branch_name,
        "base_branch": base_branch,
        "model": model,
        "max_budget_usd": max_budget,
        "duration_minutes": duration_minutes,
        "custom_prompt": custom_prompt if custom_prompt else None,
    })

    # --- Copy skills ---
    work_dir = git_ops.get_work_dir()
    _copy_skills(work_dir)

    # --- Initialize key pool ---
    key_pool = KeyPool(run_id=run_id)
    try:
        await key_pool.migrate_single_token_to_pool()
    except Exception as e:
        print(f"[agent] Key pool migration (non-fatal): {e}")
    active_key = await key_pool.get_next_key(provider="claude_code")
    if active_key:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = active_key.decrypted_value
        await db.log_audit(run_id, "key_pool_initialized", {
            "count": len(await key_pool.list_keys()),
            "active_key_id": active_key.id,
        })
    # If no keys in pool, fall through — existing env var token will be used

    # --- Build SDK options ---
    agent_defs = subagents.build_subagent_definitions()
    options = _build_sdk_options(
        model=model,
        fallback_model=fallback_model,
        work_dir=work_dir,
        custom_prompt=custom_prompt,
        duration_minutes=duration_minutes,
        max_budget=max_budget,
        session_mcp=session_mcp,
        agent_defs=agent_defs,
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
    final_status = "completed"
    total_cost = 0.0
    total_input = 0
    total_output = 0

    try:
        should_restart_client = True
        is_first_start = True
        while should_restart_client:
            should_restart_client = False
            async with ClaudeSDKClient(options=options) as client:
                if is_first_start:
                    initial = custom_prompt if custom_prompt else prompt.build_initial_prompt()
                    await client.query(initial)
                    print("[agent] Sent initial prompt")
                    is_first_start = False
                else:
                    await client.query(
                        "Continuing after key rotation. Pick up where you left off. "
                        "Check `git log --oneline -5` to see recent work."
                    )
                    print("[agent] Sent continuation prompt after key rotation")

                final_status, total_cost, total_input, total_output, should_restart_client = await _run_loop(
                    client=client,
                    run_id=run_id,
                    branch_name=branch_name,
                    custom_prompt=custom_prompt,
                    duration_minutes=duration_minutes,
                    model=model,
                    fallback_model=fallback_model,
                    base_branch=base_branch,
                    key_pool=key_pool,
                )

    except asyncio.CancelledError:
        print("[agent] Run KILLED by operator")
        final_status = "killed"
        await db.log_audit(run_id, "killed", {"elapsed_minutes": round(session_gate.elapsed_minutes(), 1)})
    except Exception as e:
        print(f"[agent] Fatal error: {e}")
        final_status = "error"
        await db.log_audit(run_id, "fatal_error", {"error": str(e)})
    finally:
        signals.stop_pulse_checker()
        signals.teardown_signal_queue()
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    await _post_run(run_id, branch_name, base_branch, final_status, total_cost, total_input, total_output)
    signals.current_run_id = None
    print(f"[agent] Run complete. Status: {final_status}, Cost: ${total_cost:.2f}, Elapsed: {session_gate.elapsed_minutes():.0f}m")


# =============================================================================
# resume_agent — resume a previous run
# =============================================================================

async def resume_agent(run_id: str, max_budget: float = 0):
    """Resume a previous run using its SDK session ID."""
    run_info = await db.get_run_for_resume(run_id)
    if not run_info:
        raise RuntimeError(f"Run {run_id} not found")
    session_id = run_info.get("sdk_session_id")

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
        try:
            git_ops._run_git(["checkout", branch_name], cwd=work_dir)
        except Exception:
            print(f"[agent] Branch {branch_name} not found — starting fresh from {base_branch}")
            git_ops.create_branch(branch_name, base_branch=base_branch)

    signals.current_run_id = run_id
    hooks.set_run_id(run_id)
    hooks.set_agent_role("worker")
    permissions.set_run_id(run_id)
    session_gate.configure(run_id, duration_minutes)
    session_mcp = session_gate.create_session_mcp_server()

    signals.init_signal_queue()
    signals.start_pulse_checker(run_id)
    await db.update_run_status(run_id, "running")
    await db.log_audit(run_id, "session_resumed", {
        "sdk_session_id": session_id[:20] if session_id else None,
        "branch": branch_name,
    })

    # --- Copy skills ---
    _copy_skills(work_dir)

    # --- Initialize key pool ---
    key_pool = KeyPool(run_id=run_id)
    active_key = await key_pool.get_next_key(provider="claude_code")
    if active_key:
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = active_key.decrypted_value

    # --- SDK options with resume ---
    agent_defs = subagents.build_subagent_definitions()
    options = _build_sdk_options(
        model=model,
        fallback_model=fallback_model,
        work_dir=work_dir,
        custom_prompt=custom_prompt,
        duration_minutes=duration_minutes,
        max_budget=max_budget,
        session_mcp=session_mcp,
        agent_defs=agent_defs,
        resume_session_id=session_id,
    )

    if session_id:
        print(f"[agent] Resuming session {session_id[:12]}...")
    else:
        print(f"[agent] No session ID — starting fresh on branch {branch_name}")

    prior_cost = run_info.get("total_cost_usd", 0) or 0
    prior_input = run_info.get("total_input_tokens", 0) or 0
    prior_output = run_info.get("total_output_tokens", 0) or 0
    final_status = "completed"
    total_cost = prior_cost
    total_input = prior_input
    total_output = prior_output

    try:
        should_restart_client = True
        is_first_start = True
        while should_restart_client:
            should_restart_client = False
            async with ClaudeSDKClient(options=options) as client:
                if is_first_start:
                    await client.query(
                        "You are resuming a previous session. Continue where you left off. "
                        "Check your recent commits with `git log --oneline -5` to remember what you were working on."
                    )
                    print("[agent] Resume prompt sent")
                    is_first_start = False
                else:
                    await client.query(
                        "Continuing after key rotation. Pick up where you left off."
                    )

                result = await _run_loop(
                    client=client,
                    run_id=run_id,
                    branch_name=branch_name,
                    custom_prompt=custom_prompt,
                    duration_minutes=duration_minutes,
                    model=model,
                    fallback_model=fallback_model,
                    base_branch=base_branch,
                    initial_cost=total_cost,
                    initial_input_tokens=total_input,
                    initial_output_tokens=total_output,
                    key_pool=key_pool,
                )
                final_status, total_cost, total_input, total_output, should_restart_client = result

    except asyncio.CancelledError:
        final_status = "killed"
    except Exception as e:
        print(f"[agent] Resume error: {e}")
        final_status = "error"
        await db.log_audit(run_id, "fatal_error", {"error": str(e)})
    finally:
        signals.stop_pulse_checker()
        signals.teardown_signal_queue()
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)

    await _post_run(run_id, branch_name, base_branch, final_status, total_cost, total_input, total_output)
    signals.current_run_id = None
    print(f"[agent] Resume complete. Status: {final_status}")
