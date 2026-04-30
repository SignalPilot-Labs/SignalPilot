---
sidebar_position: 3
---

# Custom Workflows

SignalPilot's 32 MCP tools work in any orchestration — not just the bundled skills. This guide shows how to build your own workflows.

## Pick the right tools

Start by understanding what's available:

| Task | Tools to use |
|------|-------------|
| Orient in a new schema | `list_tables`, `schema_overview`, `get_relationships` |
| Understand a specific table | `describe_table`, `explore_table`, `explore_columns` |
| Find how to join two tables | `find_join_path`, `compare_join_types` |
| Write and validate SQL | `validate_sql`, `query_database` |
| Check cost before querying | `estimate_query_cost` |
| Debug a dbt error | `dbt_error_parser`, `generate_sql_skeleton` |
| Verify a model build | `check_model_schema`, `validate_model_output`, `analyze_grain` |

## Structure your prompts

For custom workflows without skills, structure prompts to guide the tool sequence explicitly. Example:

> "First use `list_database_connections` to confirm which connection is active, then `schema_overview` to understand the database, then `find_join_path` from `orders` to `products`, then write and validate a SQL query using `validate_sql` before executing."

Or pin this in `CLAUDE.md` so you don't repeat it every session — see [CLAUDE.md recipes](/docs/workflows/claude-md-recipes).

## When to use validators

Always validate before executing on production warehouses:

```
validate_sql → confirm syntax is clean
estimate_query_cost → confirm cost is acceptable (BigQuery/Snowflake)
query_database → execute with governance
```

For DuckDB/SQLite/PostgreSQL where cost isn't an issue, you can skip `estimate_query_cost` and go straight to `validate_sql` → `query_database`.

## Project-local skills

If you want custom skill behavior for your specific project, add skill files to `.claude/skills/` in your project root:

```
your-project/
└── .claude/
    └── skills/
        └── my-custom-skill.md
```

Claude Code auto-loads files from `.claude/skills/` when present. Structure them like SignalPilot's built-in skills: trigger conditions at the top, step-by-step instructions, tool call sequences.

Example `.claude/skills/my-custom-skill.md`:

```markdown
---
name: my-etl-workflow
description: "Load when building ETL pipelines for our Snowflake warehouse."
type: skill
---

# ETL Workflow

## When this applies
- User asks to build or update an ETL pipeline
- Snowflake destination is mentioned

## Step 1 — Check source schema
Call `describe_table` on the source table first.

## Step 2 — Validate SQL
Always call `validate_sql` before `query_database`.

## Step 3 — Check cost
Call `estimate_query_cost` before any full-table scan.
```

## Using SignalPilot tools in custom agents

The MCP tools are callable from any Agent SDK that supports `streamable-http`. If you're building a custom agent:

1. Register the SignalPilot MCP server at `http://localhost:3300/mcp`
2. Call tools by name: `query_database`, `list_tables`, etc.
3. Governance runs server-side — no extra configuration needed

The 32 tools are the same regardless of which client calls them. Only the skill orchestration is Claude Code-specific.

## Multi-step query pattern

A robust pattern for ad-hoc analysis:

```
1. list_database_connections     # confirm which DB is active
2. schema_overview               # understand the shape
3. find_join_path (if joining)   # discover the join path
4. validate_sql                  # check syntax
5. estimate_query_cost           # check cost (Snowflake/BigQuery)
6. query_database                # execute
7. explore_columns (on result)   # profile the output
```

Wire this into your `CLAUDE.md` or a project-local skill for consistent behavior across sessions.
