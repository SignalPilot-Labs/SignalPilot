---
description: "Use when running Spider2 benchmarks, analyzing results, creating skills, or improving text-to-SQL accuracy. Covers the full benchmark workflow."
---

# Spider2 Benchmark Workflow

## Quick Reference

```bash
# From /workspace
python -m benchmark setup              # One-time dataset setup
python -m benchmark run --limit 5      # Quick test (5 tasks)
python -m benchmark run                # Full run (all SQLite tasks)
python -m benchmark report             # View latest results
python -m benchmark failures <run_id>  # List failures with re-run cmd
python -m benchmark compare <a> <b>    # Compare two runs
```

## Results Location

- `/bench/results/<run_id>.json` — structured data
- `/bench/results/<run_id>.md` — readable Markdown report

## Improvement Loop

1. Run baseline: `python -m benchmark run`
2. Read the `.md` report — understand failure categories
3. Create skills or fix code based on failure patterns
4. Re-run: `python -m benchmark run`
5. Compare: `python -m benchmark compare <old> <new>`

## Failure Categories

- `governance_blocked` — SQL governance rejected a valid query (engine too strict)
- `runtime_error` — Query ran but errored (syntax, missing table, etc.)
- `wrong_result` — Query ran but returned wrong rows
- `no_sql_produced` — Agent failed to produce SQL at all

## Creating Skills

Skills are JSON files in `/bench/skills/` or `/workspace/benchmark/skills/`:

```json
{
  "name": "handle_date_functions",
  "description": "Patterns for date/time SQL functions",
  "prompt": "When working with dates in SQLite, use strftime() not DATE_FORMAT()...",
  "category": "sql_patterns",
  "applicable_dbs": ["*"],
  "priority": 5
}
```

## Rules

- Always start with `--limit 5` to verify setup
- Never modify the gold dataset
- Commit skill files separately from code changes
