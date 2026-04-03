"""
Evaluation engine — matches Spider2's execution accuracy methodology.

Spider2 uses execution accuracy: compare predicted result DataFrames
against gold-standard CSVs with numeric tolerance of 1e-2.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvalResult:
    """Result of evaluating a single benchmark task."""
    instance_id: str
    correct: bool
    # Task context (filled in by the runner so reports are self-contained)
    question: str = ""
    db_id: str = ""
    # Agent output
    predicted_sql: str = ""
    gold_sql: str = ""
    predicted_rows: list[dict] = field(default_factory=list)
    gold_rows: list[dict] = field(default_factory=list)
    agent_messages: list[str] = field(default_factory=list)
    error: str = ""
    execution_ms: float = 0.0
    turns_used: int = 0
    tokens_used: int = 0
    governance_blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "instance_id": self.instance_id,
            "correct": self.correct,
            "question": self.question,
            "db_id": self.db_id,
            "predicted_sql": self.predicted_sql,
            "gold_sql": self.gold_sql,
            "error": self.error,
            "execution_ms": self.execution_ms,
            "turns_used": self.turns_used,
            "tokens_used": self.tokens_used,
            "governance_blocked": self.governance_blocked,
            "block_reason": self.block_reason,
        }
        # Only include rows/messages for failures (keeps file size sane)
        if not self.correct:
            d["predicted_rows"] = self.predicted_rows[:20]
            d["gold_rows"] = self.gold_rows[:20]
            d["agent_messages"] = [m[:500] for m in self.agent_messages[-5:]]
        return d


@dataclass
class BenchmarkMetrics:
    """Aggregated metrics from a benchmark run."""
    run_id: str
    total_tasks: int = 0
    correct: int = 0
    incorrect: int = 0
    errors: int = 0
    blocked_valid: int = 0  # false positives (valid queries blocked)
    blocked_invalid: int = 0  # true positives (bad queries blocked)
    total_execution_ms: float = 0.0
    total_turns: int = 0
    total_tokens: int = 0
    results: list[EvalResult] = field(default_factory=list)

    @property
    def execution_accuracy(self) -> float:
        return self.correct / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def error_rate(self) -> float:
        return self.errors / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def avg_execution_ms(self) -> float:
        successful = [r for r in self.results if not r.error]
        if not successful:
            return 0.0
        return sum(r.execution_ms for r in successful) / len(successful)

    @property
    def avg_turns(self) -> float:
        if not self.results:
            return 0.0
        return self.total_turns / len(self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_tasks": self.total_tasks,
            "correct": self.correct,
            "incorrect": self.incorrect,
            "errors": self.errors,
            "execution_accuracy": round(self.execution_accuracy * 100, 2),
            "error_rate": round(self.error_rate * 100, 2),
            "avg_execution_ms": round(self.avg_execution_ms, 1),
            "avg_turns": round(self.avg_turns, 1),
            "total_tokens": self.total_tokens,
            "blocked_valid_queries": self.blocked_valid,
            "results": [r.to_dict() for r in self.results],
        }

    def failure_summary(self) -> str:
        """Human/agent-readable summary of failures grouped by error pattern."""
        failures = [r for r in self.results if not r.correct]
        if not failures:
            return "All tasks passed."

        # Categorise failures
        categories: dict[str, list[EvalResult]] = {
            "governance_blocked": [],
            "runtime_error": [],
            "wrong_result": [],
            "no_sql_produced": [],
        }
        for r in failures:
            if r.governance_blocked:
                categories["governance_blocked"].append(r)
            elif r.error:
                categories["runtime_error"].append(r)
            elif not r.predicted_sql:
                categories["no_sql_produced"].append(r)
            else:
                categories["wrong_result"].append(r)

        lines = [
            f"## Failure Summary — {len(failures)}/{self.total_tasks} failed",
            "",
        ]
        for cat, items in categories.items():
            if not items:
                continue
            lines.append(f"### {cat} ({len(items)})")
            for r in items[:10]:  # cap detail at 10 per category
                lines.append(f"- **{r.instance_id}** (db={r.db_id})")
                if r.question:
                    lines.append(f"  Q: {r.question[:120]}")
                if r.predicted_sql:
                    sql_preview = r.predicted_sql.replace("\n", " ")[:120]
                    lines.append(f"  SQL: `{sql_preview}`")
                if r.error:
                    lines.append(f"  Error: {r.error[:120]}")
                if r.block_reason:
                    lines.append(f"  Blocked: {r.block_reason[:120]}")
            if len(items) > 10:
                lines.append(f"  ... and {len(items) - 10} more")
            lines.append("")

        return "\n".join(lines)


def _normalize_value(val: Any) -> Any:
    """Normalize a value for comparison."""
    if val is None or val == "" or val == "None" or val == "null":
        return 0
    if isinstance(val, str):
        val = val.strip()
        try:
            return float(val)
        except (ValueError, TypeError):
            return val.lower()
    if isinstance(val, (int, float)):
        if math.isnan(val):
            return 0
        return float(val)
    return val


def _values_match(pred: Any, gold: Any, tolerance: float = 1e-2) -> bool:
    """Compare two values with numeric tolerance."""
    pred = _normalize_value(pred)
    gold = _normalize_value(gold)

    if isinstance(pred, float) and isinstance(gold, float):
        if gold == 0:
            return abs(pred) < tolerance
        return abs(pred - gold) / max(abs(gold), 1e-10) < tolerance

    return pred == gold


def compare_results(
    predicted: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    ignore_order: bool = True,
    condition_cols: list[str] | None = None,
) -> bool:
    """
    Compare predicted and gold result sets using Spider2's methodology.

    - Column-vector comparison
    - Numeric tolerance of 1e-2
    - NaN normalized to 0
    - Optional order-independent comparison
    - Optional column subset matching
    """
    if not predicted and not gold:
        return True
    if not predicted or not gold:
        return False

    # If condition_cols specified, only compare those columns
    if condition_cols:
        pred_cols = condition_cols
        gold_cols = condition_cols
    else:
        pred_cols = list(predicted[0].keys())
        gold_cols = list(gold[0].keys())

        # Column count must match
        if len(pred_cols) != len(gold_cols):
            return False

    # Row count must match
    if len(predicted) != len(gold):
        return False

    # Extract column vectors
    def extract_col_vectors(rows: list[dict], cols: list[str]) -> list[list[Any]]:
        vectors = []
        for col in cols:
            vec = [_normalize_value(row.get(col)) for row in rows]
            vectors.append(vec)
        return vectors

    pred_vectors = extract_col_vectors(predicted, pred_cols)
    gold_vectors = extract_col_vectors(gold, gold_cols)

    if ignore_order:
        # Sort each vector independently and compare
        for i in range(len(gold_vectors)):
            pred_sorted = sorted(pred_vectors[i], key=lambda x: (isinstance(x, str), str(x)))
            gold_sorted = sorted(gold_vectors[i], key=lambda x: (isinstance(x, str), str(x)))
            for p, g in zip(pred_sorted, gold_sorted):
                if not _values_match(p, g):
                    return False
    else:
        for i in range(len(gold_vectors)):
            for p, g in zip(pred_vectors[i], gold_vectors[i]):
                if not _values_match(p, g):
                    return False

    return True


def load_gold_csv(csv_path: Path) -> list[dict[str, Any]]:
    """Load a gold-standard CSV result file."""
    if not csv_path.exists():
        return []

    rows = []
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def load_gold_sql(instance_id: str, gold_sql_dir: Path) -> str:
    """Load gold SQL for an instance."""
    sql_path = gold_sql_dir / f"{instance_id}.sql"
    if sql_path.exists():
        return sql_path.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def load_eval_config(eval_config_path: Path) -> dict[str, dict]:
    """Load per-instance evaluation config from spider2lite_eval.jsonl."""
    config = {}
    if not eval_config_path.exists():
        return config

    with open(eval_config_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            iid = entry.get("instance_id", "")
            if iid:
                config[iid] = entry
    return config


def _resolve_condition_cols(
    condition_cols: Any,
    variant_idx: int,
    gold_rows: list[dict[str, Any]],
) -> list[str] | None:
    """Convert Spider2 condition_cols (column indices) to column names.

    Spider2 eval config formats:
    - [] or None → compare all columns
    - [0] or [1] → column indices for all variants
    - [[1], [0], [0]] → per-variant column indices
    """
    if not condition_cols:
        return None

    # Determine which indices apply to this variant
    if isinstance(condition_cols[0], list):
        # Per-variant: [[1], [0], [0]]
        if variant_idx < len(condition_cols):
            col_indices = condition_cols[variant_idx]
        else:
            col_indices = condition_cols[0]
    else:
        # Shared across variants: [0] or [1]
        col_indices = condition_cols

    if not col_indices:
        return None

    # Convert indices to column names using gold CSV headers
    if not gold_rows:
        return None
    col_names = list(gold_rows[0].keys())
    result = []
    for idx in col_indices:
        if isinstance(idx, int) and 0 <= idx < len(col_names):
            result.append(col_names[idx])
    return result if result else None


def evaluate_task(
    instance_id: str,
    predicted_rows: list[dict[str, Any]],
    gold_csv_path: Path | list[Path],
    eval_config: dict | None = None,
) -> bool:
    """Evaluate a single task against its gold result.

    gold_csv_path may be a single Path or a list of Paths (variant files like
    local002_a.csv, local002_b.csv).  The task is CORRECT if it matches ANY
    variant.
    """
    if isinstance(gold_csv_path, list):
        gold_paths = gold_csv_path
    else:
        gold_paths = [gold_csv_path]

    ignore_order = True
    raw_condition_cols = None

    if eval_config:
        ignore_order = eval_config.get("ignore_order", True)
        raw_condition_cols = eval_config.get("condition_cols")

    for i, path in enumerate(gold_paths):
        gold_rows = load_gold_csv(path)
        condition_cols = _resolve_condition_cols(raw_condition_cols, i, gold_rows)
        if compare_results(
            predicted_rows,
            gold_rows,
            ignore_order=ignore_order,
            condition_cols=condition_cols,
        ):
            return True

    return False


def parse_query_result_to_rows(result_text: str) -> list[dict[str, Any]]:
    """Parse SignalPilot query_database output back into rows."""
    lines = result_text.strip().split("\n")

    # Find header line (first non-empty line before the separator)
    header_line = None
    data_start = 0
    for i, line in enumerate(lines):
        if line.startswith("---") or line.startswith("==="):
            header_line = lines[i - 1] if i > 0 else None
            data_start = i + 1
            break

    if header_line is None:
        # Try CSV-like parsing
        try:
            reader = csv.DictReader(io.StringIO(result_text))
            return [dict(row) for row in reader]
        except Exception:
            return []

    columns = [c.strip() for c in header_line.split("|")]
    rows = []
    for line in lines[data_start:]:
        if not line.strip() or line.startswith("[") or line.startswith("..."):
            continue
        values = [v.strip() for v in line.split("|")]
        if len(values) == len(columns):
            rows.append(dict(zip(columns, values)))

    return rows
