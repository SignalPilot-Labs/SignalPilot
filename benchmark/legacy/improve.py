"""
Improvement agent — analyzes benchmark failures and proposes fixes.

Uses Claude Agent SDK to:
1. Load failure report from the last benchmark run
2. Classify each failure (wrong table, wrong column, blocked valid, etc.)
3. Generate proposed changes (new skills, schema annotations, prompt tweaks)
4. Save improvements to skills/ directory
5. Optionally re-run benchmark with improvements applied
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from .config import RESULTS_DIR, SKILLS_DIR


ANALYSIS_PROMPT = """You are an expert SQL benchmark analyst. Analyze the following benchmark failures and propose improvements.

## Benchmark Results

{results_json}

## Task

For each failure, classify it into one of these categories:
1. **wrong_table** — Agent selected the wrong table(s)
2. **wrong_column** — Agent used wrong column names
3. **wrong_aggregation** — Incorrect GROUP BY, COUNT, SUM, etc.
4. **wrong_join** — Missing or incorrect JOIN condition
5. **wrong_filter** — Incorrect WHERE/HAVING clause
6. **syntax_error** — SQL syntax issue
7. **governance_blocked** — Valid query was blocked by SignalPilot governance
8. **timeout** — Agent ran out of turns/time
9. **no_result** — Agent didn't produce a final query
10. **other** — Other failure mode

Then for each category with failures, propose concrete improvements as new **skills** (prompt strategies).

## Output Format

Output a JSON object with this structure:
```json
{{
    "analysis": [
        {{
            "instance_id": "...",
            "category": "wrong_table",
            "root_cause": "Agent didn't check all tables before selecting",
            "suggested_fix": "Explore all tables systematically"
        }}
    ],
    "new_skills": [
        {{
            "name": "skill_name",
            "description": "What this skill does",
            "prompt": "The prompt fragment to inject",
            "category": "sql_generation",
            "applicable_dbs": ["sqlite"],
            "priority": 5
        }}
    ],
    "summary": {{
        "total_analyzed": 10,
        "categories": {{"wrong_table": 3, "wrong_column": 2, ...}},
        "key_insight": "Most failures stem from..."
    }}
}}
```

Focus on actionable improvements that would help the agent get more answers correct on the next run.
"""


async def analyze_run(run_id: str, save_skills: bool = True) -> dict:
    """Analyze a benchmark run's failures and propose improvements."""
    results_file = RESULTS_DIR / f"{run_id}.json"
    if not results_file.exists():
        print(f"Run not found: {results_file}")
        return {}

    data = json.loads(results_file.read_text())
    failures = [r for r in data.get("results", []) if not r.get("correct", False)]

    if not failures:
        print("No failures to analyze!")
        return {"analysis": [], "new_skills": [], "summary": {"key_insight": "All tasks passed!"}}

    print(f"Analyzing {len(failures)} failures from run {run_id}...")

    # Prepare results for the analysis prompt
    results_json = json.dumps({
        "run_id": run_id,
        "execution_accuracy": data.get("execution_accuracy", 0),
        "total_tasks": data.get("total_tasks", 0),
        "failures": failures,
    }, indent=2)

    prompt = ANALYSIS_PROMPT.format(results_json=results_json)

    options = ClaudeAgentOptions(
        system_prompt="You are a benchmark analysis expert. Output only valid JSON.",
        model="claude-sonnet-4-6",
        max_turns=200,
        permission_mode="bypassPermissions",
    )

    full_response = ""
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        full_response += block.text
    except Exception as e:
        print(f"Analysis failed: {e}")
        return {}

    # Parse JSON from response
    try:
        # Find JSON block in response
        import re
        json_match = re.search(r"```json\s*\n(.+?)```", full_response, re.DOTALL)
        if json_match:
            analysis = json.loads(json_match.group(1))
        else:
            analysis = json.loads(full_response)
    except json.JSONDecodeError:
        print("Failed to parse analysis JSON. Raw response:")
        print(full_response[:500])
        return {}

    # Print summary
    summary = analysis.get("summary", {})
    print(f"\nAnalysis Summary:")
    print(f"  Failures analyzed: {summary.get('total_analyzed', len(failures))}")
    categories = summary.get("categories", {})
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    print(f"  Key insight: {summary.get('key_insight', 'N/A')}")

    # Save new skills
    new_skills = analysis.get("new_skills", [])
    if new_skills and save_skills:
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        skills_file = SKILLS_DIR / f"improvements_{run_id}.json"
        skills_file.write_text(json.dumps(new_skills, indent=2))
        print(f"\n{len(new_skills)} new skills saved to: {skills_file}")
        for skill in new_skills:
            print(f"  + {skill['name']}: {skill['description']}")

    # Save full analysis
    analysis_file = RESULTS_DIR / f"{run_id}_analysis.json"
    analysis_file.write_text(json.dumps(analysis, indent=2))
    print(f"Full analysis saved to: {analysis_file}")

    return analysis


async def improvement_loop(
    base_run_id: str,
    iterations: int = 3,
    task_limit: int = 0,
    model: str = "claude-sonnet-4-6",
):
    """Run the recursive improvement loop.

    1. Analyze failures from base run
    2. Generate new skills
    3. Re-run benchmark with new skills
    4. Compare results
    5. Keep improvements if accuracy increased, revert if not
    6. Repeat
    """
    from .run import run_benchmark, compare_runs
    from .config import BenchmarkConfig

    current_run_id = base_run_id
    best_accuracy = 0.0

    # Load base accuracy
    base_file = RESULTS_DIR / f"{base_run_id}.json"
    if base_file.exists():
        base_data = json.loads(base_file.read_text())
        best_accuracy = base_data.get("execution_accuracy", 0)

    print(f"\n{'='*60}")
    print(f"IMPROVEMENT LOOP — Starting from {base_run_id} ({best_accuracy}%)")
    print(f"{'='*60}")

    for iteration in range(1, iterations + 1):
        print(f"\n--- Iteration {iteration}/{iterations} ---")

        # Step 1: Analyze failures
        analysis = await analyze_run(current_run_id)
        if not analysis.get("new_skills"):
            print("No new skills generated. Stopping.")
            break

        # Step 2: Collect all skill names
        all_skills = []
        for f in SKILLS_DIR.glob("improvements_*.json"):
            skills_data = json.loads(f.read_text())
            all_skills.extend(s["name"] for s in skills_data)

        # Step 3: Re-run benchmark with accumulated skills
        config = BenchmarkConfig(
            subset="sqlite",
            task_limit=task_limit,
            model=model,
            skills=all_skills,
            run_id=f"improve_{iteration}_{time.strftime('%Y%m%d_%H%M%S')}",
        )

        metrics = await run_benchmark(config)

        # Step 4: Compare
        new_accuracy = metrics.execution_accuracy * 100
        print(f"\nIteration {iteration}: {best_accuracy}% → {new_accuracy}%")

        if new_accuracy > best_accuracy:
            print(f"  IMPROVED by {new_accuracy - best_accuracy:.1f}%! Keeping changes.")
            best_accuracy = new_accuracy
            current_run_id = config.run_id
        else:
            print(f"  No improvement (or regression). Reverting last skill additions.")
            # Remove the last improvement file
            last_skills_file = SKILLS_DIR / f"improvements_{current_run_id}.json"
            if last_skills_file.exists():
                last_skills_file.unlink()
            current_run_id = config.run_id  # Still use this as the reference

    print(f"\n{'='*60}")
    print(f"IMPROVEMENT LOOP COMPLETE")
    print(f"Best accuracy: {best_accuracy}%")
    print(f"{'='*60}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Spider2 Benchmark Improvement Agent")
    parser.add_argument("command", choices=["analyze", "loop"],
                        help="analyze: analyze one run. loop: recursive improvement")
    parser.add_argument("run_id", help="Run ID to analyze or start from")
    parser.add_argument("--iterations", type=int, default=3,
                        help="Number of improvement iterations (for loop)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Task limit for re-runs")
    parser.add_argument("--model", default="claude-sonnet-4-6",
                        help="Model for re-runs")
    parser.add_argument("--no-save", action="store_true",
                        help="Don't save generated skills")

    args = parser.parse_args()

    if args.command == "analyze":
        asyncio.run(analyze_run(args.run_id, save_skills=not args.no_save))
    elif args.command == "loop":
        asyncio.run(improvement_loop(
            base_run_id=args.run_id,
            iterations=args.iterations,
            task_limit=args.limit,
            model=args.model,
        ))


if __name__ == "__main__":
    main()
