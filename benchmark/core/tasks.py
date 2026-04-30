"""Task + eval-config loading for Spider2-DBT."""

from __future__ import annotations

import json
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
    """Load task definition from the suite's JSONL file."""
    with open(config.task_jsonl) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            task = json.loads(line)
            if task["instance_id"] == instance_id:
                return task
    raise ValueError(f"Task '{instance_id}' not found in {config.task_jsonl}")


def _normalize_eval_entry(entry: dict) -> dict:
    """Normalize flat-format Spider2 eval entries into nested format expected by sql_comparator."""
    if "evaluation" in entry:
        return entry
    if "condition_cols" not in entry:
        return entry
    normalized = dict(entry)
    condition_cols = normalized.pop("condition_cols")
    ignore_order = normalized.pop("ignore_order", True)
    normalized["evaluation"] = {
        "parameters": {
            "condition_cols": condition_cols,
            "ignore_orders": [ignore_order],
        }
    }
    return normalized


def load_eval_config_for_suite(instance_id: str, config: "SuiteConfig") -> dict | None:
    """Load evaluation config for this task from the suite's eval JSONL file.

    Normalizes flat Spider2 eval entries into the nested format expected by sql_comparator.
    Returns None if the file does not exist or the entry is not found.
    """
    if not config.eval_jsonl.exists():
        return None
    with open(config.eval_jsonl) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry["instance_id"] == instance_id:
                return _normalize_eval_entry(entry)
    return None
