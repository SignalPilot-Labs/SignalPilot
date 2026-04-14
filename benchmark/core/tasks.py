"""Task + eval-config loading for Spider2-DBT."""

from __future__ import annotations

import json

from .paths import EVAL_JSONL, TASK_JSONL


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
