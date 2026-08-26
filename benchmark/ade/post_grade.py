"""Post-grade review: resume the agent's conversation after grading.

Copies gold solution into the workdir, then sends a follow-up message
to the SAME agent session asking it to compare, fix, and write a report.

Usage:
    python -m benchmark.ade.post_grade <task_id> [--results-dir DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from ..agent.sdk_runner import run_sdk_agent
from ..core.logging import log, log_separator
from .tasks import load_task


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DBT_BIN = shutil.which("dbt") or "dbt"


def _inject_gold(work_dir: Path, task: dict) -> None:
    """Copy gold solution into _gold/ and apply patch to show correct files."""
    gold_dir = work_dir / "_gold"
    if gold_dir.exists():
        shutil.rmtree(gold_dir)
    gold_dir.mkdir()

    task_dir = task.get("task_dir")
    if not task_dir:
        # Fall back to ade-bench path
        ade_bench = Path(os.environ.get("ADE_BENCH_DIR", ""))
        task_dir = ade_bench / "tasks" / task["task_id"]

    # Copy task.yaml
    if task_dir.exists():
        task_yaml = task_dir / "task.yaml"
        if task_yaml.exists():
            shutil.copy2(task_yaml, gold_dir / "task.yaml")

    # Copy the changes.patch (the gold solution)
    sol_dir = task_dir / "solutions" if task_dir.exists() else None
    if sol_dir and sol_dir.exists():
        for item in sol_dir.iterdir():
            dst = gold_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)

    # Create _gold_applied/ by checking out the git baseline and applying the patch
    gold_applied = work_dir / "_gold_applied"
    if gold_applied.exists():
        shutil.rmtree(gold_applied)
    gold_applied.mkdir()

    patch_file = gold_dir / "changes.patch"
    if patch_file.exists():
        import subprocess
        # Extract baseline files from git (post-setup state)
        for subdir in ("models", "snapshots", "macros", "seeds"):
            baseline_dir = work_dir / subdir
            if baseline_dir.exists():
                # Use git show HEAD:<path> to get pre-agent state
                result = subprocess.run(
                    ["git", "ls-tree", "-r", "--name-only", "HEAD", f"{subdir}/"],
                    cwd=str(work_dir), capture_output=True, text=True,
                )
                for rel_path in result.stdout.strip().split("\n"):
                    if not rel_path:
                        continue
                    dst = gold_applied / rel_path
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    content = subprocess.run(
                        ["git", "show", f"HEAD:{rel_path}"],
                        cwd=str(work_dir), capture_output=True,
                    )
                    if content.returncode == 0:
                        dst.write_bytes(content.stdout)

        # Apply gold patch on top of baseline
        subprocess.run(
            ["patch", "--fuzz=3", "-p1", "-d", str(gold_applied), "-i", str(patch_file)],
            capture_output=True,
        )
        log(f"Applied gold patch to {gold_applied}")

    log(f"Injected gold solution into {gold_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-grade review")
    parser.add_argument("task_id", help="ADE-bench task ID")
    parser.add_argument(
        "--results-dir",
        default="benchmark/results/ade",
        help="Results directory",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Model to use for review",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=60,
        help="Max turns for review",
    )
    args = parser.parse_args()

    task_id = args.task_id
    task = load_task(task_id)

    # Find the workdir from the results
    results_dir = Path(args.results_dir)
    work_dir = results_dir / task_id / "workdir"

    # If workdir doesn't exist in results, check the standard ADE work location
    if not work_dir.exists():
        import os
        ade_work_base = Path(os.environ.get("ADE_WORK_DIR", "benchmark/_ade_workdir"))
        work_dir = ade_work_base / task_id
        if not work_dir.exists():
            log(f"Workdir not found for {task_id}", "ERROR")
            sys.exit(1)

    log_separator(f"Post-Grade Review: {task_id}")

    # Step 1: Inject gold solution
    _inject_gold(work_dir, task)

    # Step 2: Read the review prompt
    review_prompt_path = PROMPTS_DIR / "post_grade_review.md"
    review_prompt = review_prompt_path.read_text()

    # Step 3: Resume the agent conversation with the review prompt
    log("Resuming agent session for post-grade review...")

    result = asyncio.run(
        run_sdk_agent(
            prompt=review_prompt,
            work_dir=work_dir,
            model=args.model,
            max_turns=args.max_turns,
            timeout=600,
            label="post-grade-review",
            continue_conversation=True,
        )
    )

    # Step 4: Save the review result
    review_result_path = results_dir / task_id / "post_grade_result.json"
    review_result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(review_result_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    log(f"Post-grade review saved to {review_result_path}")

    # Check if failure_report.html was created
    report_path = work_dir / "failure_report.html"
    if report_path.exists():
        # Copy report to results
        dst = results_dir / task_id / "failure_report.html"
        shutil.copy2(report_path, dst)
        log(f"Failure report: {dst}")
    else:
        log("No failure_report.html generated", "WARN")


if __name__ == "__main__":
    main()
