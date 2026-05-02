"""LLM judge for fail-cause analysis.

For each task in a run, sends the question, predicted SQL+CSV, and gold CSV to a
Claude judge model and writes a category + root-cause verdict to judge.jsonl.

This is *not* used as a gating signal — the official Spider2 metric stays the headline.
The judge is for offline triage: how many fails are missing-column vs wrong-filter vs
wrong-aggregation, so we know where to invest.

Uses the Claude Agent SDK (same auth path as the runner) so it works with
CLAUDE_CODE_OAUTH_TOKEN.

Usage:
    python -m benchmark.evaluation.judge benchmark/results/lite-strat10
    python -m benchmark.evaluation.judge benchmark/results/lite-strat10 --only-failed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from ..core.logging import log
from ..core.suite import BenchmarkSuite, get_suite_config
from ..core.tasks import load_task_for_suite

JUDGE_MODEL = "claude-sonnet-4-6"

JUDGE_SYSTEM = """\
You are an evaluator analyzing why a SQL benchmark task failed against the official Spider2
gold standard. The official metric is value-vector matching: each gold column must match
some pred column by sorted values (with 1e-2 numeric tolerance, column-name agnostic).

Given the question, the predicted SQL+result, and the gold result, classify the failure into
EXACTLY ONE category, then give a 1-2 sentence root cause and a one-sentence fix hint.

Categories:
- missing_column: pred is missing a column the gold has (most common — usually the natural PK)
- extra_filter_missing: pred didn't apply a filter the question implied
- wrong_aggregation: GROUP BY grain wrong, or wrong aggregate (SUM vs AVG, COUNT vs COUNT DISTINCT)
- wrong_join_or_fanout: JOIN duplicated rows or used the wrong join type
- wrong_value_calc: arithmetic/derivation differs from gold definition
- wrong_filter_predicate: a filter is present but uses wrong threshold/value
- interpretation_drift: the agent answered a different question than was asked
- numeric_precision: values match conceptually but rounding/precision differs (rare with tolerance)
- result_truncated: pred has fewer rows than gold (LIMIT applied wrongly, or filter too strict)
- result_excess: pred has more rows than gold (missing filter, or wrong DISTINCT)
- spurious_pass: official metric passed but pred is semantically wrong (rare; only for PASS rows)
- other: doesn't fit above; explain briefly

Output STRICT JSON only, no prose, no markdown:
{"category": "<one of the above>", "root_cause": "<1-2 sentences>", "fix_hint": "<one specific change>"}
"""


def _trim_csv(text: str, max_lines: int = 12) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    head = lines[: max_lines - 1]
    return "\n".join(head) + f"\n... ({len(lines) - max_lines + 1} more rows)"


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def _build_user_msg(question: str, pred_sql: str, pred_csv: str, gold_csv: str) -> str:
    return (
        f"QUESTION:\n{question}\n\n"
        f"PRED SQL:\n{pred_sql}\n\n"
        f"PRED CSV:\n{_trim_csv(pred_csv)}\n\n"
        f"GOLD CSV:\n{_trim_csv(gold_csv)}\n"
    )


def _extract_json(text: str) -> dict:
    """Extract a JSON object from a possibly-fenced response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find a {...} substring
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {"category": "other", "root_cause": text[:300], "fix_hint": ""}


async def _judge_task(instance_id: str, work_dir: Path, config) -> dict:
    """Judge one task. Returns a verdict dict."""
    task = load_task_for_suite(instance_id, config)
    question = task.get("instruction") or task.get("question", "")

    pred_sql = _read_text(work_dir / "result.sql")
    pred_csv = _read_text(work_dir / "result.csv")

    exec_result = config.gold_dir / "exec_result"
    pat = re.compile(rf"^{re.escape(instance_id)}(_[a-z])?\.csv$")
    gold_csvs = sorted(p for p in exec_result.iterdir() if pat.match(p.name)) if exec_result.is_dir() else []
    gold_csv = _read_text(gold_csvs[0]) if gold_csvs else ""

    if not (pred_csv and gold_csv):
        return {
            "instance_id": instance_id,
            "category": "missing_artifacts",
            "root_cause": "result.csv or gold csv missing — agent likely didn't reach the save step.",
            "fix_hint": "Ensure agent reaches the save step within the turn budget.",
        }

    user_msg = _build_user_msg(question, pred_sql, pred_csv, gold_csv)

    options = ClaudeAgentOptions(
        model=JUDGE_MODEL,
        max_turns=1,
        permission_mode="bypassPermissions",
        system_prompt=JUDGE_SYSTEM,
        # No MCP, no skills — judge is a pure-text classifier.
    )

    response_text = ""
    async for msg in query(prompt=user_msg, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    response_text += block.text
        elif isinstance(msg, ResultMessage):
            break

    verdict = _extract_json(response_text)
    verdict["instance_id"] = instance_id
    return verdict


def _parse_run_log(log_path: Path) -> list[tuple[str, str]]:
    """Parse a run log for (instance_id, status) pairs.

    Accepts both sequential format (===== START local054) and parallel format
    (lines containing 'END local054  status=PASS').
    """
    tasks: dict[str, str] = {}

    # Match local* (SQLite), bq*/ga* (BigQuery), sf*/sf_bq* (Snowflake) instance ids.
    _ID = r"(?:local|sf_bq|sf|bq|ga)\w+"
    parallel_re = re.compile(rf"\bEND ({_ID})\s+status=(PASS|FAIL|SKIP|ERROR)\b")
    parallel_skip_re = re.compile(rf"\[({_ID})\] result\.csv already present")
    seq_start_re = re.compile(rf"^===== START ({_ID})")

    cur_id: str | None = None
    cur_status: str | None = None
    for line in log_path.read_text().splitlines():
        # Sequential format
        m = seq_start_re.search(line)
        if m:
            cur_id = m.group(1)
            cur_status = None
            continue
        if "RESULT: PASS" in line:
            cur_status = "PASS"
            continue
        if "RESULT: FAIL" in line or "RESULT: ERROR" in line:
            cur_status = "FAIL"
            continue
        if line.startswith("===== END ") and cur_id:
            tasks[cur_id] = cur_status or "UNKNOWN"
            cur_id = None
            continue
        # Parallel format
        m = parallel_re.search(line)
        if m:
            tasks[m.group(1)] = m.group(2)
            continue
        m = parallel_skip_re.search(line)
        if m and m.group(1) not in tasks:
            tasks[m.group(1)] = "SKIP"

    return list(tasks.items())


async def _amain() -> None:
    parser = argparse.ArgumentParser(description="LLM-judge fail-cause analysis for a Spider2 run.")
    parser.add_argument("results_dir", help="Run results dir (contains run.log)")
    parser.add_argument("--suite", default="spider2-lite", choices=["spider2-lite", "spider2-snowflake"])
    parser.add_argument("--only-failed", action="store_true", help="Only judge tasks marked FAIL/ERROR in run.log")
    parser.add_argument("--out", help="Output JSONL path (default: <results_dir>/judge.jsonl)")
    args = parser.parse_args()

    suite = BenchmarkSuite(args.suite)
    config = get_suite_config(suite)

    results_dir = Path(args.results_dir)
    log_path = results_dir / "parallel.log"
    if not log_path.exists():
        log_path = results_dir / "run.log"
    if not log_path.exists():
        print(f"ERROR: no run.log or parallel.log in {results_dir}", file=sys.stderr)
        sys.exit(2)

    tasks = _parse_run_log(log_path)
    if args.only_failed:
        tasks = [t for t in tasks if t[1] != "PASS"]

    if not tasks:
        print("No tasks to judge.")
        return

    out_path = Path(args.out) if args.out else (results_dir / "judge.jsonl")
    log(f"Judging {len(tasks)} tasks -> {out_path}")

    with out_path.open("w") as f:
        for instance_id, status in tasks:
            work_dir = config.work_dir / instance_id
            try:
                verdict = await _judge_task(instance_id, work_dir, config)
            except Exception as e:
                verdict = {
                    "instance_id": instance_id,
                    "category": "judge_error",
                    "root_cause": str(e)[:200],
                    "fix_hint": "",
                }
            verdict["official_status"] = status
            f.write(json.dumps(verdict) + "\n")
            f.flush()
            log(f"  {instance_id} [{status}] -> {verdict.get('category', '?')}")

    counts: dict[str, int] = {}
    with out_path.open() as f:
        for line in f:
            v = json.loads(line)
            if v.get("official_status") != "PASS":
                cat = v.get("category", "?")
                counts[cat] = counts.get(cat, 0) + 1

    print("\nFail-cause distribution (failed tasks):")
    for cat, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {cat}")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
