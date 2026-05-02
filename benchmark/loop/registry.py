"""Append-only task-status registry across rounds.

Format: JSONL at benchmark/results/registry.jsonl. One line per (round, task).

Each entry:
    {
      "round": 3,
      "task": "local074",
      "status": "PASS"|"FAIL"|"ERROR"|"SKIP",
      "fail_category": null|"missing_column"|...,
      "elapsed_s": 211.1,
      "cost_usd": 0.21,
      "fired_checks": ["id_with_name"],
      "timestamp": "2026-05-01T17:30:00Z"
    }

The registry is read to:
- Identify the passing-pool (any task with most-recent status = PASS)
- Identify the failing-pool (most-recent status = FAIL) for targeted re-attempts
- Detect regressions (task was PASS in round N, FAIL in round N+1)
- Avoid recently-run tasks when sampling fresh exploration
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..core.paths import PROJECT_ROOT

REGISTRY_PATH = PROJECT_ROOT / "benchmark" / "results" / "registry.jsonl"


@dataclass
class TaskRecord:
    round: int
    task: str
    status: str  # PASS / FAIL / ERROR / SKIP
    fail_category: str | None = None
    elapsed_s: float | None = None
    cost_usd: float | None = None
    fired_checks: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_json(self) -> str:
        d = self.__dict__.copy()
        if not d["timestamp"]:
            d["timestamp"] = datetime.now(timezone.utc).isoformat()
        return json.dumps(d)


def append_record(record: TaskRecord, path: Path = REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(record.to_json() + "\n")


def load_all(path: Path = REGISTRY_PATH) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def latest_status_per_task(records: list[dict]) -> dict[str, dict]:
    """Returns {task: most_recent_record}."""
    by_task: dict[str, dict] = {}
    for r in sorted(records, key=lambda x: x["round"]):
        by_task[r["task"]] = r
    return by_task


def passing_pool(records: list[dict]) -> set[str]:
    """Tasks whose most-recent status is PASS."""
    return {t for t, r in latest_status_per_task(records).items() if r["status"] == "PASS"}


def failing_pool(records: list[dict]) -> set[str]:
    """Tasks whose most-recent status is FAIL."""
    return {t for t, r in latest_status_per_task(records).items() if r["status"] == "FAIL"}


def recently_run(records: list[dict], rounds_back: int) -> set[str]:
    """Tasks run in the last N rounds (any status)."""
    if not records:
        return set()
    max_round = max(r["round"] for r in records)
    threshold = max_round - rounds_back + 1
    return {r["task"] for r in records if r["round"] >= threshold}


def regressions(records: list[dict]) -> list[tuple[str, int, int]]:
    """Detect (task, round_passed, round_failed) for any task that went PASS → FAIL."""
    by_task: dict[str, list[dict]] = {}
    for r in records:
        by_task.setdefault(r["task"], []).append(r)
    out: list[tuple[str, int, int]] = []
    for task, rs in by_task.items():
        rs.sort(key=lambda x: x["round"])
        last_pass: int | None = None
        for r in rs:
            if r["status"] == "PASS":
                last_pass = r["round"]
            elif r["status"] == "FAIL" and last_pass is not None:
                out.append((task, last_pass, r["round"]))
                last_pass = None  # only flag first regression after a pass
    return out


def current_round(records: list[dict]) -> int:
    """The next round number (max existing + 1, or 1 if empty)."""
    if not records:
        return 1
    return max(r["round"] for r in records) + 1
