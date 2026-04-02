"""Prompt management — loads all prompts from markdown files in the prompts/ directory."""

import os
from pathlib import Path

# Prompts directory lives alongside the agent code in the Docker image,
# but is also at /workspace/self-improve/prompts when mounted
_PROMPTS_DIR = Path("/workspace/self-improve/prompts")
_FALLBACK_DIR = Path(__file__).parent.parent / "prompts"


def _load(name: str) -> str:
    """Load a prompt markdown file by name (without .md extension)."""
    for d in (_PROMPTS_DIR, _FALLBACK_DIR):
        path = d / f"{name}.md"
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"Prompt file not found: {name}.md")


def build_system_prompt(
    custom_focus: str | None = None,
    duration_minutes: float = 0,
) -> dict:
    """Build the system prompt from markdown files."""
    parts = [_load("system"), _load("session-gate")]

    if duration_minutes > 0:
        if duration_minutes >= 60:
            h = int(duration_minutes // 60)
            m = int(duration_minutes % 60)
            dur = f"{h}h {m}m" if m else f"{h}h"
        else:
            dur = f"{int(duration_minutes)}m"
        parts.append(_load("timed-session").replace("{duration}", dur))

    if custom_focus:
        parts.append(f"## Additional Focus\n{custom_focus}")

    return {
        "type": "preset",
        "preset": "claude_code",
        "append": "\n\n".join(parts),
    }


def build_initial_prompt() -> str:
    return _load("initial")


def build_continuation_prompt() -> str:
    return _load("continuation-default")


def build_ceo_continuation(
    round_num: int,
    elapsed_minutes: float,
    duration_minutes: float,
    tool_summary: str,
    files_changed: str,
    commits: str,
    cost_so_far: float,
    round_summary: str,
    original_prompt: str,
) -> str:
    """Build the CEO/PM continuation prompt with round context and original mission."""
    if duration_minutes > 0:
        pct = min(100, int((elapsed_minutes / duration_minutes) * 100))
        elapsed_str = f"{int(elapsed_minutes)}m"
        duration_str = f"{int(duration_minutes)}m"
    else:
        pct = 0
        elapsed_str = f"{int(elapsed_minutes)}m"
        duration_str = "unlimited"

    template = _load("ceo-continuation")
    # Escape braces in user-derived content to prevent KeyError when diffs/commits
    # contain literal { or } characters (common in code snippets and JSON).
    # NOTE: This escaping is specific to str.format(). If the template is changed
    # to use f-strings or a different templating engine, this function must be updated.
    def _safe(val: str) -> str:
        return val.replace("{", "{{").replace("}", "}}")

    return template.format(
        round_num=round_num,
        elapsed=elapsed_str,
        duration=duration_str,
        pct_complete=pct,
        tool_summary=_safe(tool_summary or "none"),
        files_changed=_safe(files_changed or "none"),
        commits=_safe(commits or "none"),
        cost_so_far=f"{cost_so_far:.2f}",
        round_summary=_safe(round_summary or "No summary available."),
        original_prompt=_safe(original_prompt or "General self-improvement pass on the codebase."),
    )


def build_stop_prompt(reason: str = "") -> str:
    base = _load("stop")
    if reason:
        return f"Stop reason: {reason}\n\n{base}"
    return base


def load_agent_prompt(agent_name: str) -> str:
    """Load a subagent prompt from prompts/agent-{name}.md."""
    return _load(f"agent-{agent_name}")
