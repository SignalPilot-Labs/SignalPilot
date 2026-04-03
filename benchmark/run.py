"""
Main benchmark runner — orchestrates Spider2 benchmark runs.

Usage:
    # Setup Spider2 dataset
    python -m benchmark.run setup

    # Run SQLite subset (default)
    python -m benchmark.run

    # Run specific tasks
    python -m benchmark.run --ids local001,local002

    # Run with specific model
    python -m benchmark.run --model claude-opus-4-6

    # Run with skills
    python -m benchmark.run --skills schema_explorer,sqlite_expert

    # Run with task limit
    python -m benchmark.run --limit 10

    # Compare two runs
    python -m benchmark.run compare run_001 run_002

    # Init skills table in DB
    python -m benchmark.run init-skills --db path/to/skills.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

from .config import (
    BenchmarkConfig,
    RESULTS_DIR,
    SIGNALPILOT_GATEWAY_URL,
    SPIDER2_EVAL_CONFIG,
    SPIDER2_GOLD_EXEC,
    SPIDER2_GOLD_SQL,
)
from .eval import BenchmarkMetrics, EvalResult, load_eval_config, load_gold_sql
from .setup_spider2 import get_external_knowledge, get_sqlite_db_path, list_sqlite_tasks, setup_spider2
from .skills import get_skills, init_skills_table, skills_to_prompt


async def run_benchmark(config: BenchmarkConfig) -> BenchmarkMetrics:
    """Run the full benchmark."""
    from .agent_runner import TaskContext, register_sqlite_connection, run_task_with_eval

    run_id = config.run_id or f"run_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    config.run_id = run_id

    print(f"\n{'='*60}")
    print(f"SignalPilot Spider2 Benchmark — Run: {run_id}")
    print(f"{'='*60}")
    print(f"Model: {config.model}")
    print(f"Max turns per task: {config.max_turns}")
    print(f"Budget per task: ${config.max_budget_usd}")
    print(f"Governance: {'enabled' if config.use_governance else 'disabled'}")

    # Load tasks
    tasks = list_sqlite_tasks()
    if not tasks:
        print("ERROR: No SQLite tasks found. Run: python -m benchmark.run setup")
        return BenchmarkMetrics(run_id=run_id)

    # Filter by instance IDs if specified
    if config.instance_ids:
        tasks = [t for t in tasks if t["instance_id"] in config.instance_ids]

    # Apply task limit
    if config.task_limit > 0:
        tasks = tasks[:config.task_limit]

    print(f"Tasks to run: {len(tasks)}")

    # Skills are loaded per-task to include db-specific skills
    base_skill_names = config.skills if config.skills else None

    # Load evaluation config
    eval_configs = load_eval_config(SPIDER2_EVAL_CONFIG)

    # Prepare metrics
    metrics = BenchmarkMetrics(run_id=run_id, total_tasks=len(tasks))

    print(f"\n{'─'*60}")

    for i, task_data in enumerate(tasks):
        instance_id = task_data["instance_id"]
        db_id = task_data.get("db", task_data.get("db_id", ""))
        question = task_data.get("question", task_data.get("instruction", ""))
        ext_knowledge_file = task_data.get("external_knowledge", "")

        print(f"\n[{i+1}/{len(tasks)}] {instance_id} (db={db_id})")
        print(f"  Q: {question[:100]}{'...' if len(question) > 100 else ''}")

        # Find SQLite database
        db_path = get_sqlite_db_path(db_id)
        if not db_path:
            print(f"  SKIP: SQLite database not found for db_id={db_id}")
            metrics.errors += 1
            metrics.results.append(EvalResult(
                instance_id=instance_id,
                correct=False,
                error=f"Database not found: {db_id}",
            ))
            continue

        # Register connection
        connection_name = f"spider2_{db_id}"
        registered = await register_sqlite_connection(
            connection_name=connection_name,
            db_path=str(db_path),
            gateway_url=SIGNALPILOT_GATEWAY_URL,
        )
        if not registered:
            print(f"  SKIP: Could not register connection for {db_id}")
            metrics.errors += 1
            metrics.results.append(EvalResult(
                instance_id=instance_id,
                correct=False,
                error=f"Connection registration failed: {db_id}",
            ))
            continue

        # Load external knowledge
        ext_knowledge = ""
        if ext_knowledge_file:
            ext_knowledge = get_external_knowledge(ext_knowledge_file)
            if ext_knowledge:
                print(f"  External knowledge: {ext_knowledge_file} ({len(ext_knowledge)} chars)")

        # Load skills (per-task to include db-specific skills)
        skills = get_skills(
            names=base_skill_names,
            db_type="sqlite",
            db_id=db_id,
        )
        skills_prompt = skills_to_prompt(skills)

        # Build task context
        task_ctx = TaskContext(
            instance_id=instance_id,
            question=question,
            db_id=db_id,
            db_path=str(db_path),
            external_knowledge=ext_knowledge,
            skills_prompt=skills_prompt,
            connection_name=connection_name,
        )

        # Find gold result — prefer variant files (local002_a.csv, local002_b.csv …)
        # then fall back to bare instance_id.csv
        gold_csv_variants = sorted(SPIDER2_GOLD_EXEC.glob(f"{instance_id}_*.csv"))
        if not gold_csv_variants:
            bare = SPIDER2_GOLD_EXEC / f"{instance_id}.csv"
            gold_csv_variants = [bare] if bare.exists() else []
        eval_config = eval_configs.get(instance_id)

        # Run task
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

        # Update metrics
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

    # Print summary
    print(f"\n{'='*60}")
    print(f"RESULTS — {run_id}")
    print(f"{'='*60}")
    print(f"Execution Accuracy: {metrics.execution_accuracy*100:.1f}%")
    print(f"  Correct: {metrics.correct}/{metrics.total_tasks}")
    print(f"  Incorrect: {metrics.incorrect}/{metrics.total_tasks}")
    print(f"  Errors: {metrics.errors}/{metrics.total_tasks}")
    print(f"  False Positives (blocked valid): {metrics.blocked_valid}")
    print(f"Avg Execution: {metrics.avg_execution_ms:.0f}ms per task")
    print(f"Avg Turns: {metrics.avg_turns:.1f}")
    print(f"Total Tokens: {metrics.total_tokens:,}")
    print(f"{'='*60}")

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_file = RESULTS_DIR / f"{run_id}.json"
    results_file.write_text(json.dumps(metrics.to_dict(), indent=2))
    print(f"\nResults saved to: {results_file}")

    # Write human/agent-readable Markdown report
    report_file = RESULTS_DIR / f"{run_id}.md"
    report_file.write_text(_generate_report(metrics, config))
    print(f"Report saved to:  {report_file}")

    return metrics


def _generate_report(metrics: BenchmarkMetrics, config: BenchmarkConfig) -> str:
    """Generate a Markdown report that an agent can read to understand results."""
    lines = [
        f"# Benchmark Report — {metrics.run_id}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Execution Accuracy | **{metrics.execution_accuracy*100:.1f}%** |",
        f"| Correct | {metrics.correct}/{metrics.total_tasks} |",
        f"| Incorrect | {metrics.incorrect}/{metrics.total_tasks} |",
        f"| Errors | {metrics.errors}/{metrics.total_tasks} |",
        f"| False Positives (blocked valid) | {metrics.blocked_valid} |",
        f"| Avg Execution Time | {metrics.avg_execution_ms:.0f}ms |",
        f"| Avg Agent Turns | {metrics.avg_turns:.1f} |",
        f"| Total Tokens | {metrics.total_tokens:,} |",
        "",
        "## Config",
        "",
        f"- Model: `{config.model}`",
        f"- Max turns: {config.max_turns}",
        f"- Budget/task: ${config.max_budget_usd}",
        f"- Governance: {'enabled' if config.use_governance else 'disabled'}",
        f"- Skills: {config.skills or '(all defaults)'}",
        "",
    ]

    # Failure details
    lines.append(metrics.failure_summary())

    # Correct tasks (just IDs for reference)
    correct = [r for r in metrics.results if r.correct]
    if correct:
        lines.extend([
            "",
            f"## Correct Tasks ({len(correct)})",
            "",
        ])
        for r in correct:
            lines.append(f"- {r.instance_id} ({r.execution_ms:.0f}ms, {r.turns_used} turns)")

    # Actionable next steps
    lines.extend([
        "",
        "## Suggested Next Steps",
        "",
    ])

    if metrics.blocked_valid > 0:
        lines.append(f"- **{metrics.blocked_valid} valid queries were blocked** — review governance rules in `gateway/engine/__init__.py`")
    if metrics.errors > 0:
        lines.append(f"- **{metrics.errors} tasks errored** — check agent logs and connection registration")

    wrong = [r for r in metrics.results if not r.correct and not r.error and not r.governance_blocked]
    if wrong:
        # Identify most common db_ids in failures
        db_counts: dict[str, int] = {}
        for r in wrong:
            db_counts[r.db_id] = db_counts.get(r.db_id, 0) + 1
        top_dbs = sorted(db_counts.items(), key=lambda x: -x[1])[:5]
        lines.append(f"- **{len(wrong)} wrong results** — top failing databases: {', '.join(f'{db}({n})' for db, n in top_dbs)}")
        lines.append("- Consider adding schema-specific skills for these databases")
        lines.append("- Run `python -m benchmark.improve analyze {run_id}` for detailed failure classification")

    if metrics.execution_accuracy > 0:
        lines.append(f"- Run `python -m benchmark.improve loop {metrics.run_id}` to auto-generate improvement skills")

    return "\n".join(lines)


def compare_runs(run_id_a: str, run_id_b: str):
    """Compare two benchmark runs."""
    file_a = RESULTS_DIR / f"{run_id_a}.json"
    file_b = RESULTS_DIR / f"{run_id_b}.json"

    if not file_a.exists():
        print(f"Run not found: {file_a}")
        return
    if not file_b.exists():
        print(f"Run not found: {file_b}")
        return

    a = json.loads(file_a.read_text())
    b = json.loads(file_b.read_text())

    print(f"\n{'='*60}")
    print(f"COMPARISON: {run_id_a} vs {run_id_b}")
    print(f"{'='*60}")

    metrics = [
        ("Execution Accuracy", "execution_accuracy", "%"),
        ("Error Rate", "error_rate", "%"),
        ("Avg Execution (ms)", "avg_execution_ms", "ms"),
        ("Avg Turns", "avg_turns", ""),
        ("Total Tokens", "total_tokens", ""),
    ]

    for label, key, unit in metrics:
        va = a.get(key, 0)
        vb = b.get(key, 0)
        delta = vb - va
        arrow = "+" if delta > 0 else ""
        print(f"  {label:25s}  {va:>10.1f}{unit}  →  {vb:>10.1f}{unit}  ({arrow}{delta:.1f})")

    # Per-task diff
    a_results = {r["instance_id"]: r for r in a.get("results", [])}
    b_results = {r["instance_id"]: r for r in b.get("results", [])}

    flipped_correct = []
    flipped_incorrect = []
    for iid in set(a_results) & set(b_results):
        a_ok = a_results[iid].get("correct", False)
        b_ok = b_results[iid].get("correct", False)
        if not a_ok and b_ok:
            flipped_correct.append(iid)
        elif a_ok and not b_ok:
            flipped_incorrect.append(iid)

    if flipped_correct:
        print(f"\n  Newly correct ({len(flipped_correct)}):")
        for iid in flipped_correct[:10]:
            print(f"    + {iid}")

    if flipped_incorrect:
        print(f"\n  Newly incorrect ({len(flipped_incorrect)}):")
        for iid in flipped_incorrect[:10]:
            print(f"    - {iid}")

    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="SignalPilot Spider2 Benchmark")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "setup", "compare", "init-skills", "list-results",
                                 "report", "list-tasks", "failures"],
                        help="Command to execute")
    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Claude model to use")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit number of tasks (0 = all)")
    parser.add_argument("--ids", default="",
                        help="Comma-separated instance IDs to run")
    parser.add_argument("--skills", default="",
                        help="Comma-separated skill names to load")
    parser.add_argument("--max-turns", type=int, default=30,
                        help="Max agent turns per task")
    parser.add_argument("--budget", type=float, default=5.0,
                        help="Max budget per task in USD")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Number of parallel tasks")
    parser.add_argument("--no-governance", action="store_true",
                        help="Disable SignalPilot governance")
    parser.add_argument("--run-id", default="",
                        help="Custom run ID")
    parser.add_argument("--db", default="",
                        help="Path to skills database")
    parser.add_argument("--force", action="store_true",
                        help="Force re-download of Spider2 data")
    parser.add_argument("--retry-failures", default="",
                        help="Re-run only failed tasks from a previous run ID")
    parser.add_argument("--filter-db", default="",
                        help="Only run tasks for a specific db_id")
    parser.add_argument("run_ids", nargs="*",
                        help="Run IDs for compare/report/failures commands")

    args = parser.parse_args()

    if args.command == "setup":
        setup_spider2(force=args.force)
        return

    if args.command == "init-skills":
        if not args.db:
            print("Usage: python -m benchmark.run init-skills --db path/to/skills.db")
            sys.exit(1)
        init_skills_table(args.db)
        print(f"Skills table initialized in {args.db}")
        return

    if args.command == "list-results":
        if not RESULTS_DIR.exists():
            print("No results yet.")
            return
        for f in sorted(RESULTS_DIR.glob("*.json")):
            data = json.loads(f.read_text())
            ea = data.get("execution_accuracy", 0)
            total = data.get("total_tasks", 0)
            correct = data.get("correct", 0)
            errors = data.get("errors", 0)
            report_exists = (RESULTS_DIR / f"{f.stem}.md").exists()
            print(f"  {f.stem}: {ea}% ({correct}/{total} correct, {errors} errors) {'[report]' if report_exists else ''}")
        return

    if args.command == "report":
        if not args.run_ids:
            # Show latest report
            reports = sorted(RESULTS_DIR.glob("*.md")) if RESULTS_DIR.exists() else []
            if not reports:
                print("No reports found. Run a benchmark first.")
                sys.exit(1)
            print(reports[-1].read_text())
        else:
            report_path = RESULTS_DIR / f"{args.run_ids[0]}.md"
            if report_path.exists():
                print(report_path.read_text())
            else:
                print(f"Report not found: {report_path}")
                print("(Reports are auto-generated alongside each run. Check list-results.)")
        return

    if args.command == "list-tasks":
        try:
            tasks = list_sqlite_tasks()
        except FileNotFoundError as e:
            print(str(e))
            sys.exit(1)
        # Group by db_id
        by_db: dict[str, list[dict]] = {}
        for t in tasks:
            db = t.get("db", t.get("db_id", "unknown"))
            by_db.setdefault(db, []).append(t)
        print(f"Spider2-Lite SQLite tasks: {len(tasks)} total, {len(by_db)} databases\n")
        for db, db_tasks in sorted(by_db.items()):
            gold_count = sum(
                1 for t in db_tasks
                if (
                    list(SPIDER2_GOLD_EXEC.glob(f"{t['instance_id']}_*.csv"))
                    or (SPIDER2_GOLD_EXEC / f"{t['instance_id']}.csv").exists()
                )
            )
            print(f"  {db} ({len(db_tasks)} tasks, {gold_count} with gold CSV)")
            if args.limit:
                for t in db_tasks[:args.limit]:
                    q = t.get("question", t.get("instruction", ""))[:80]
                    print(f"    {t['instance_id']}: {q}")
                if len(db_tasks) > args.limit:
                    print(f"    ... and {len(db_tasks) - args.limit} more")
        return

    if args.command == "failures":
        if not args.run_ids:
            # Use latest run
            jsons = sorted(RESULTS_DIR.glob("*.json")) if RESULTS_DIR.exists() else []
            if not jsons:
                print("No runs found.")
                sys.exit(1)
            run_file = jsons[-1]
        else:
            run_file = RESULTS_DIR / f"{args.run_ids[0]}.json"
        if not run_file.exists():
            print(f"Run not found: {run_file}")
            sys.exit(1)
        data = json.loads(run_file.read_text())
        failures = [r for r in data.get("results", []) if not r.get("correct")]
        if not failures:
            print(f"No failures in {run_file.stem} — all {data.get('total_tasks', 0)} tasks passed!")
            return
        print(f"Failures from {run_file.stem}: {len(failures)}/{data.get('total_tasks', 0)}\n")
        # Print as a copyable --ids list
        fail_ids = [r["instance_id"] for r in failures]
        print(f"Re-run command:\n  python -m benchmark run --ids {','.join(fail_ids)}\n")
        for r in failures:
            status = "BLOCKED" if r.get("governance_blocked") else "ERROR" if r.get("error") else "WRONG"
            print(f"  [{status:7s}] {r['instance_id']} (db={r.get('db_id', '?')})")
            if r.get("question"):
                print(f"           Q: {r['question'][:100]}")
            if r.get("predicted_sql"):
                sql = r["predicted_sql"].replace("\n", " ")[:100]
                print(f"           SQL: {sql}")
            if r.get("error"):
                print(f"           Error: {r['error'][:100]}")
            if r.get("block_reason"):
                print(f"           Blocked: {r['block_reason'][:100]}")
        return

    if args.command == "compare":
        if len(args.run_ids) != 2:
            print("Usage: python -m benchmark compare <run_id_a> <run_id_b>")
            sys.exit(1)
        compare_runs(args.run_ids[0], args.run_ids[1])
        return

    # --- Build instance_ids list ---
    instance_ids = args.ids.split(",") if args.ids else []

    # --retry-failures: extract failed IDs from a previous run
    if args.retry_failures:
        prev_file = RESULTS_DIR / f"{args.retry_failures}.json"
        if not prev_file.exists():
            print(f"Run not found for --retry-failures: {prev_file}")
            sys.exit(1)
        prev = json.loads(prev_file.read_text())
        fail_ids = [r["instance_id"] for r in prev.get("results", []) if not r.get("correct")]
        if not fail_ids:
            print(f"No failures in {args.retry_failures} — nothing to retry.")
            return
        print(f"Retrying {len(fail_ids)} failures from {args.retry_failures}")
        instance_ids = fail_ids

    # --filter-db: only tasks for a specific database
    if args.filter_db:
        try:
            tasks = list_sqlite_tasks()
        except FileNotFoundError as e:
            print(str(e))
            sys.exit(1)
        db_ids = [t["instance_id"] for t in tasks
                  if t.get("db", t.get("db_id", "")) == args.filter_db]
        if not db_ids:
            print(f"No tasks found for db_id={args.filter_db}")
            sys.exit(1)
        print(f"Filtering to {len(db_ids)} tasks for db={args.filter_db}")
        if instance_ids:
            instance_ids = [i for i in instance_ids if i in db_ids]
        else:
            instance_ids = db_ids

    # Run benchmark
    config = BenchmarkConfig(
        subset="sqlite",
        task_limit=args.limit,
        instance_ids=instance_ids,
        model=args.model,
        max_turns=args.max_turns,
        max_budget_usd=args.budget,
        concurrency=args.concurrency,
        use_governance=not args.no_governance,
        skills=args.skills.split(",") if args.skills else [],
        run_id=args.run_id,
    )

    asyncio.run(run_benchmark(config))


if __name__ == "__main__":
    main()
