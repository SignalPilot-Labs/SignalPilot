"""Task + eval-config loading for Spider2 benchmark suites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from .paths import EVAL_JSONL, TASK_JSONL

if TYPE_CHECKING:
    from .suite import SuiteConfig


def load_task(instance_id: str) -> dict:
    """Load task definition from the Spider2-DBT JSONL file."""
    with open(TASK_JSONL) as f:
        for line in f:
            task = json.loads(line.strip())
            if task["instance_id"] == instance_id:
                return task
    raise ValueError(f"Task '{instance_id}' not found in {TASK_JSONL}")


def load_eval_config(instance_id: str) -> dict | None:
    """Load evaluation config for this task from spider2_eval.jsonl."""
    with open(EVAL_JSONL) as f:
        for line in f:
            entry = json.loads(line.strip())
            if entry["instance_id"] == instance_id:
                return entry
    return None


def load_task_for_suite(instance_id: str, config: "SuiteConfig") -> dict:
    """Load task definition from the suite-specific JSONL file.

    For spider2-lite tasks, the returned dict includes a 'type' field
    (sqlite | snowflake | bigquery) that the runner uses to pick the DB backend.
    """
    jsonl_path: Path = config.task_jsonl
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            task = json.loads(line)
            if task.get("instance_id") == instance_id:
                return task
    raise ValueError(f"Task '{instance_id}' not found in {jsonl_path}")


def load_eval_config_for_suite(instance_id: str, config: "SuiteConfig") -> dict | None:
    """Load evaluation config for a suite-specific task.

    Returns the raw eval entry dict, or None if not found.
    """
    jsonl_path: Path = config.eval_jsonl
    if not jsonl_path.exists():
        return None
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("instance_id") == instance_id:
                return entry
    return None
