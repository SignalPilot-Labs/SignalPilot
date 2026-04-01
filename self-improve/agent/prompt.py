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


def build_escalating_continuation(round_num: int, elapsed_pct: float) -> str:
    """Load the right phase-specific continuation prompt based on elapsed time."""
    if elapsed_pct <= 0:
        return build_continuation_prompt()

    if elapsed_pct < 0.15:
        phase = "phase1"
    elif elapsed_pct < 0.30:
        phase = "phase2"
    elif elapsed_pct < 0.50:
        phase = "phase3"
    elif elapsed_pct < 0.70:
        phase = "phase4"
    elif elapsed_pct < 0.85:
        phase = "phase5"
    else:
        phase = "phase6"

    try:
        return _load(f"continuation-{phase}")
    except FileNotFoundError:
        return build_continuation_prompt()


def build_stop_prompt(reason: str = "") -> str:
    base = _load("stop")
    if reason:
        return f"Stop reason: {reason}\n\n{base}"
    return base
