"""ADE-bench task loading from task.yaml files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _ade_bench_dir() -> Path:
    """Return the ade-bench repo root (sibling of SignalPilot in SPEcosystem)."""
    import os
    env_path = os.environ.get("ADE_BENCH_DIR")
    if env_path:
        return Path(env_path)
    # Default: sibling directory
    return Path(__file__).resolve().parent.parent.parent.parent / "ade-bench"


def load_task(task_id: str) -> dict[str, Any]:
    """Load a task definition from its task.yaml file.

    Returns a dict with keys: task_id, prompt, db_name, project_name,
    solution_seeds, test_setup, setup_dir, tests_dir, macros_dir, seeds_dir,
    difficulty, tags, and the raw task_yaml.
    """
    ade_dir = _ade_bench_dir()
    task_dir = ade_dir / "tasks" / task_id
    task_yaml_path = task_dir / "task.yaml"

    if not task_yaml_path.exists():
        raise FileNotFoundError(f"Task not found: {task_yaml_path}")

    with open(task_yaml_path) as f:
        raw = yaml.safe_load(f)

    # Find the duckdb variant
    duckdb_variant = None
    for v in raw.get("variants", []):
        if v.get("db_type") == "duckdb" and v.get("project_type") == "dbt":
            duckdb_variant = v
            break

    if not duckdb_variant:
        raise ValueError(f"Task {task_id} has no duckdb+dbt variant")

    # Extract prompt (first/base prompt — official ADE-bench uses "base" key)
    prompts = raw.get("prompts", [])
    prompt_text = prompts[0]["prompt"] if prompts else raw.get("description", "")

    # Solution seeds for evaluation (preserve full config)
    solution_seeds = []
    solution_seed_configs = []
    for seed in raw.get("solution_seeds", []):
        solution_seeds.append(seed["table_name"])
        solution_seed_configs.append({
            "table_name": seed["table_name"],
            "include_columns": seed.get("include_columns", []),
            "exclude_columns": seed.get("exclude_columns", []),
            "alternates": seed.get("alternates", []),
            "exclude_tests": seed.get("exclude_tests", []),
        })

    return {
        "task_id": task_id,
        "prompt": prompt_text,
        "db_name": duckdb_variant["db_name"],
        "project_name": duckdb_variant["project_name"],
        "solution_seeds": solution_seeds,
        "solution_seed_configs": solution_seed_configs,
        "test_setup": raw.get("test_setup", ""),
        "setup_script": task_dir / "setup.sh" if (task_dir / "setup.sh").exists() else None,
        "setup_dir": task_dir / "setup" if (task_dir / "setup").exists() else None,
        "tests_dir": task_dir / "tests" if (task_dir / "tests").exists() else None,
        "macros_dir": task_dir / "macros" if (task_dir / "macros").exists() else None,
        "seeds_dir": task_dir / "seeds" if (task_dir / "seeds").exists() else None,
        "difficulty": raw.get("difficulty", "unknown"),
        "tags": raw.get("tags", []),
        "task_yaml": raw,
    }


def list_ready_tasks() -> list[str]:
    """Return task IDs where status == ready and a duckdb+dbt variant exists."""
    ade_dir = _ade_bench_dir()
    tasks_dir = ade_dir / "tasks"
    ready = []
    for task_dir in sorted(tasks_dir.iterdir()):
        task_yaml = task_dir / "task.yaml"
        if not task_yaml.exists():
            continue
        with open(task_yaml) as f:
            raw = yaml.safe_load(f)
        if raw.get("status") != "ready":
            continue
        # Must have a duckdb+dbt variant
        has_duckdb = any(
            v.get("db_type") == "duckdb" and v.get("project_type") == "dbt"
            for v in raw.get("variants", [])
        )
        if has_duckdb:
            ready.append(raw["task_id"])
    return ready
