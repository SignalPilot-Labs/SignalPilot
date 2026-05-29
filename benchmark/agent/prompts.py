"""Prompt builders for the main dbt agent."""

from __future__ import annotations

from pathlib import Path


def build_agent_prompt(
    instance_id: str,
    instruction: str,
    work_dir: Path,
    eval_critical_models: set[str],
    max_turns: int = 200,
) -> str:
    """Build the agent prompt — just the task description.

    All context discovery (models, columns, dependencies, sources) is left to
    the agent via the plugin skills (scan_project.py, dbt_project_map) and MCP tools.
    """
    return f"DBT TASK: {instruction}"
