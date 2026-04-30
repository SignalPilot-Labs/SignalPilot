---
sidebar_position: 7
---

# Plugin Overview

The [SignalPilot Claude Code plugin](https://github.com/SignalPilot-Labs/signalpilot-plugin) adds battle-tested dbt and SQL skills to Claude Code — the same skills that power the Spider 2.0-DBT SOTA (51.56%, #1 Apr 2026).

## What the plugin adds

- **9 skills** — markdown knowledge files that auto-load into Claude Code's context based on task relevance. They teach Claude which MCP tools to call, in what order, and what to watch out for.
- **1 verifier agent** — a 7-check post-build quality protocol that runs after `dbt run` and returns a structured receipt.

The plugin is **Claude Code-specific**. Skills and the verifier agent don't run in Cursor, Codex, or other clients. The 32 MCP tools work everywhere, but skill orchestration is Claude Code-only.

## Install

```bash
claude plugin marketplace add SignalPilot-Labs/signalpilot-plugin
claude plugin install signalpilot-dbt@signalpilot
```

## What a skill is

A skill is a markdown file registered with Claude Code. When a task matches the skill's trigger conditions, Claude Code loads it into the context automatically — you don't need to prompt for it. The skill describes:

- When it activates (e.g. "load at Step 1 before exploring the dbt project")
- What to do (step-by-step instructions, tool call sequences)
- Common gotchas for that dialect or task type

## The verifier agent

After `dbt run`, the verifier agent performs 7 checks and returns a structured receipt:

1. Column alignment — materialized columns match YML-declared columns
2. Row count validation — model is not empty, not over-fanned-out
3. Fan-out detection — join fan-out ratios within expected bounds
4. NULL scan — required columns have no unexpected NULLs
5. Source row counts — upstream sources have expected row counts
6. Schema comparison — no unintended column additions or removals
7. Grain analysis — cardinality per key matches the model's declared grain

See [Verifier agent](/docs/plugin/verifier-agent) for full details.

## Included skills

| Skill | When it loads |
|-------|--------------|
| `dbt-workflow` | Step 1 of any dbt task — full 5-step lifecycle |
| `dbt-write` | Step 4, when writing SQL models |
| `dbt-debugging` | When `dbt run` or `dbt parse` fails |
| `dbt-date-spines` | When date hazards are reported |
| `sql-workflow` | Before writing any SQL query |
| `duckdb-sql` | When hitting DuckDB-specific syntax |
| `snowflake-sql` | Snowflake-specific patterns |
| `bigquery-sql` | BigQuery-specific patterns |
| `sqlite-sql` | SQLite-specific patterns |

See [Skills overview](/docs/plugin/skills-overview) and [Skills reference](/docs/plugin/skills-reference) for details.

## Updating

```bash
claude plugin update signalpilot-dbt@signalpilot
```
