"""
PostgreSQL benchmark runner — runs pg-benchmark.jsonl tasks against pre-registered
PostgreSQL connections via SignalPilot MCP tools.

Usage:
    python -m benchmark.run_pg
    python -m benchmark.run_pg --limit 5
    python -m benchmark.run_pg --model claude-opus-4-6
    python -m benchmark.run_pg --ids pg_ent_001,pg_wh_002
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

from .agent_runner import TaskContext, run_task_with_eval
from .config import BenchmarkConfig, DATASETS_DIR, RESULTS_DIR
from .eval import BenchmarkMetrics, EvalResult, load_eval_config
from .run import _generate_report
from .skills import get_skills, skills_to_prompt

PG_TASKS_PATH = DATASETS_DIR / "pg-benchmark.jsonl"
PG_EVAL_CONFIG_PATH = DATASETS_DIR / "pg-eval.jsonl"
PG_GOLD_DIR = DATASETS_DIR / "pg-gold"


def load_pg_tasks(path: Path = PG_TASKS_PATH) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"pg-benchmark.jsonl not found at {path}")
    tasks = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    return tasks


def _build_pg_system_prompt(task: TaskContext, config: BenchmarkConfig) -> str:
    parts = [
        "You are a SQL expert tasked with answering a natural language question by querying a PostgreSQL database.",
        "",
        "## Instructions",
        f"- The database is registered as connection '{task.connection_name}' in SignalPilot",
        "- Use `query_database` to run SQL queries (read-only, governed by SignalPilot)",
        "- Use `list_database_connections` to verify the connection exists",
        "- First explore the database schema to understand the tables and columns",
        "- Then write and execute SQL to answer the question",
        "- Your goal is to produce the CORRECT result set that answers the question",
        "",
        "## Approach",
        "1. List connections to confirm the database is available",
        "2. Explore schema using INFORMATION_SCHEMA views:",
        "   - `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'`",
        "   - `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '<table>'`",
        "   - Or query pg_catalog.pg_tables / pg_catalog.pg_attribute for low-level metadata",
        "3. Sample data from relevant tables to understand formats and values",
        "4. Write your SQL query using standard PostgreSQL syntax",
        "5. Execute it and verify the results make sense",
        "6. If results look wrong, iterate on your query",
        "",
        "## PostgreSQL-Specific Tips",
        "- Use ILIKE for case-insensitive string matching",
        "- Use EXTRACT() or DATE_PART() for date/time operations",
        "- Prefer INFORMATION_SCHEMA over sqlite_master (this is PostgreSQL, not SQLite)",
        "- CTEs (WITH clauses) and window functions are fully supported",
        "",
        "## Output Format",
        "After you have the final correct result, output EXACTLY this block:",
        "```sql",
        "-- FINAL SQL",
        "<your final SQL query here>",
        "```",
        "",
        "Then output the results in a clearly marked block.",
        "If the query returns results through query_database, that is sufficient.",
    ]

    if task.external_knowledge:
        parts.extend([
            "",
            "## External Knowledge",
            task.external_knowledge,
        ])

    if task.skills_prompt:
        parts.extend(["", task.skills_prompt])

    return "\n".join(parts)


def _build_pg_user_prompt(task: TaskContext) -> str:
    return (
        f"Database: {task.connection_name} (PostgreSQL)\n\n"
        f"Question: {task.question}\n\n"
        "Please explore the database schema and write a SQL query to answer this question. "
        "Show me the final SQL and results."
    )


async def run_pg_benchmark(config: BenchmarkConfig) -> BenchmarkMetrics:
    """Run the full PostgreSQL benchmark."""
    # Monkey-patch system/user prompt builders for PG before importing run_task
    import benchmark.agent_runner as agent_runner
    _orig_system = agent_runner._build_system_prompt
    _orig_user = agent_runner._build_user_prompt
    agent_runner._build_system_prompt = _build_pg_system_prompt
    agent_runner._build_user_prompt = _build_pg_user_prompt

    run_id = config.run_id or f"pg_run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    config.run_id = run_id

    print(f"\n{'='*60}")
    print(f"SignalPilot PG Benchmark — Run: {run_id}")
    print(f"{'='*60}")
    print(f"Model: {config.model}")
    print(f"Max turns per task: {config.max_turns}")
    print(f"Budget per task: ${config.max_budget_usd}")

    tasks = load_pg_tasks()
    if config.instance_ids:
        tasks = [t for t in tasks if t["instance_id"] in config.instance_ids]
    if config.task_limit > 0:
        tasks = tasks[:config.task_limit]

    print(f"Tasks to run: {len(tasks)}")

    skills = get_skills(names=config.skills if config.skills else None, db_type="postgresql")
    skills_prompt = skills_to_prompt(skills)
    if skills:
        print(f"Skills loaded: {[s.name for s in skills]}")

    eval_configs = load_eval_config(PG_EVAL_CONFIG_PATH)
    metrics = BenchmarkMetrics(run_id=run_id, total_tasks=len(tasks))

    print(f"\n{'─'*60}")

    for i, task_data in enumerate(tasks):
        instance_id = task_data["instance_id"]
        db_id = task_data["db"]
        question = task_data.get("question", task_data.get("instruction", ""))
        ext_knowledge = task_data.get("external_knowledge") or ""

        print(f"\n[{i+1}/{len(tasks)}] {instance_id} (db={db_id})")
        print(f"  Q: {question[:100]}{'...' if len(question) > 100 else ''}")

        # Connection name is the db field value directly (already registered)
        connection_name = db_id

        task_ctx = TaskContext(
            instance_id=instance_id,
            question=question,
            db_id=db_id,
            db_path="",  # not applicable for PG
            external_knowledge=ext_knowledge,
            skills_prompt=skills_prompt,
            connection_name=connection_name,
        )

        # Resolve gold CSV variants
        gold_csv_variants = sorted(PG_GOLD_DIR.glob(f"{instance_id}_*.csv"))
        if not gold_csv_variants:
            bare = PG_GOLD_DIR / f"{instance_id}.csv"
            gold_csv_variants = [bare] if bare.exists() else []

        eval_config = eval_configs.get(instance_id)

        try:
            result = await run_task_with_eval(
                task=task_ctx,
                config=config,
                gold_csv_path=gold_csv_variants if gold_csv_variants else None,
                eval_config=eval_config,
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            result = EvalResult(
                instance_id=instance_id,
                correct=False,
                error=str(e),
            )

        metrics.results.append(result)
        if result.error:
            metrics.errors += 1
            print(f"  ERROR: {result.error[:100]}")
        elif result.correct:
            metrics.correct += 1
            print(f"  CORRECT ({result.execution_ms:.0f}ms, {result.turns_used} turns)")
        else:
            metrics.incorrect += 1
            print(f"  INCORRECT ({result.execution_ms:.0f}ms, {result.turns_used} turns)")
            if result.governance_blocked:
                metrics.blocked_valid += 1
                print(f"  Blocked: {result.block_reason[:80]}")

        metrics.total_execution_ms += result.execution_ms
        metrics.total_turns += result.turns_used
        metrics.total_tokens += result.tokens_used

    # Restore original prompt builders
    agent_runner._build_system_prompt = _orig_system
    agent_runner._build_user_prompt = _orig_user

    print(f"\n{'='*60}")
    print(f"RESULTS — {run_id}")
    print(f"{'='*60}")
    print(f"Execution Accuracy: {metrics.execution_accuracy*100:.1f}%")
    print(f"  Correct: {metrics.correct}/{metrics.total_tasks}")
    print(f"  Incorrect: {metrics.incorrect}/{metrics.total_tasks}")
    print(f"  Errors: {metrics.errors}/{metrics.total_tasks}")
    print(f"Avg Execution: {metrics.avg_execution_ms:.0f}ms per task")
    print(f"Avg Turns: {metrics.avg_turns:.1f}")
    print(f"Total Tokens: {metrics.total_tokens:,}")
    print(f"{'='*60}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = RESULTS_DIR / f"{run_id}.json"
    results_file.write_text(json.dumps(metrics.to_dict(), indent=2))
    print(f"\nResults saved to: {results_file}")

    report_file = RESULTS_DIR / f"{run_id}.md"
    report_file.write_text(_generate_report(metrics, config))
    print(f"Report saved to:  {report_file}")

    return metrics


def main():
    parser = argparse.ArgumentParser(description="SignalPilot PostgreSQL Benchmark")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Claude model to use")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of tasks (0 = all)")
    parser.add_argument("--ids", default="", help="Comma-separated instance IDs to run")
    parser.add_argument("--skills", default="", help="Comma-separated skill names to load")
    parser.add_argument("--max-turns", type=int, default=30, help="Max agent turns per task")
    parser.add_argument("--budget", type=float, default=5.0, help="Max budget per task in USD")
    parser.add_argument("--no-governance", action="store_true", help="Disable SignalPilot governance")
    parser.add_argument("--run-id", default="", help="Custom run ID")
    args = parser.parse_args()

    config = BenchmarkConfig(
        subset="postgresql",
        task_limit=args.limit,
        instance_ids=args.ids.split(",") if args.ids else [],
        model=args.model,
        max_turns=args.max_turns,
        max_budget_usd=args.budget,
        use_governance=not args.no_governance,
        skills=args.skills.split(",") if args.skills else [],
        run_id=args.run_id,
    )

    asyncio.run(run_pg_benchmark(config))


if __name__ == "__main__":
    main()
