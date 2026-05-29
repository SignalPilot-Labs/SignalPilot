# Benchmark Architecture — Complete Knowledge Map

## Three Suites
- **spider2-dbt** (BenchmarkSuite.DBT): Agent writes dbt SQL models, builds with dbt, evaluated by DuckDB table comparison
- **spider2-snowflake** (BenchmarkSuite.SNOWFLAKE): Agent writes SQL queries against Snowflake, saves result.csv
- **spider2-lite** (BenchmarkSuite.LITE): Agent writes SQL against SQLite/BigQuery/Snowflake, saves result.csv

## Entry Points
- `python -m benchmark.run_direct <task>` — routes via `run_direct.py` based on `--suite` flag
- Default (no --suite or spider2-dbt) → `runners/direct.py:main()`
- `--suite spider2-snowflake|spider2-lite` → `runners/sql_runner.py:main(suite)`
- Parallel mode: `execute_dbt_task()` and `execute_sql_task()` are async, called from batch runner

## DBT Runner Pipeline (runners/direct.py)
1. `prepare_workdir()` — copies task from spider2 examples, runs `dbt deps`, removes packages.yml, git init
2. `write_claude_md()` — writes CLAUDE.md with MCP tool catalog into workdir
3. `register_local_connection()` — registers DuckDB via gateway HTTP API
4. `_snapshot_reference_tables()` — captures pre-existing table row counts/columns/samples to reference_snapshot.md
5. `create_sql_templates()` — pre-populates SQL stubs for YML-defined models with no SQL
6. `create_ephemeral_stubs()` — auto-creates ephemeral stubs for ref() targets that are raw DuckDB tables
7. `run_sdk_agent()` — Claude Agent SDK with system prompt + user prompt
8. `_flush_and_release()` — DuckDB CHECKPOINT + delete MCP connection
9. `evaluate()` — DuckDB table comparison against gold

## SQL Runner Pipeline (runners/sql_runner.py)
1. `prepare_sql_workdir()` — creates empty dir, copies .mcp.json, skills, schema files, SQLite DB
2. `write_sql_claude_md()` — writes CLAUDE.md with connection info + MCP tools
3. `_register_connection()` — registers Snowflake/SQLite/BigQuery connection
4. `run_sdk_agent()` — with `build_sql_agent_prompt()` and `system_general.md` system prompt
5. `evaluate_sql()` — CSV comparison against gold CSV(s)

## Prompt Layers (what agent sees)
| Layer | File | Owns |
|-------|------|------|
| System prompt (DBT) | `prompts/dbt_local_system.md` | Workflow steps, skill overriding rules |
| System prompt (SQL) | `prompts/system_general.md` | MCP tool catalog, connection info, workflow |
| User prompt (DBT) | `agent/prompts.py:build_agent_prompt()` | Just `TASK: {instruction}` — minimal |
| User prompt (SQL) | `agent/sql_prompts.py:build_sql_agent_prompt()` | Full workflow, verification steps, rules, backend tips |
| CLAUDE.md | Written by `workdir.py` | Task instructions, MCP tool list, connection name |
| Skills | `skills/*/SKILL.md` | Deep domain knowledge per topic |
| Subagent: verifier | `prompts/dbt_verify_subagent.md` | 7-check verification protocol |
| Subagent: explorer | `prompts/dbt_explorer_subagent.md` | Pre-build reference snapshot |

## Skills (benchmark/skills/)
- **sql-workflow**: Schema exploration, output shape inference, CTE building, verification loop, error recovery, saving
- **dbt-workflow**: Output shape inference, incremental models, period-over-period, what to trust in YML, grain derivation
- **dbt-write**: Column naming, types, sibling models, lookup joins, JOIN defaults, materialization, packages, filters
- **dbt-debugging**: Duplicate YML patches, ref errors, passthrough warnings, current_date fixes, DuckDB errors, zero-row, fan-out
- **dbt-date-spines**: Fixing current_date/now() in model files, package model overrides, finding right date
- **duckdb-sql**: Integer division, DATE_TRUNC, INTERVAL, QUALIFY, date parsing, date spines, type casting
- **snowflake-sql**: QUALIFY, ILIKE, LATERAL FLATTEN, VARIANT, date functions, time travel
- **bigquery-sql**: UNNEST, backtick tables, DATE_DIFF/DATE_ADD, EXCEPT/REPLACE, STRUCT, partitioned tables, Spider2 patterns
- **sqlite-sql**: substr/instr, ||, LIKE, date(), CAST, no FULL OUTER JOIN, GROUP_CONCAT, typeof

## Suite → Skills mapping (core/suite.py)
- DBT: dbt-workflow, dbt-debugging, dbt-date-spines, duckdb-sql
- Snowflake: sql-workflow, snowflake-sql
- Lite: sql-workflow + backend-specific (sqlite-sql OR bigquery-sql OR snowflake-sql) — selected by `_get_skill_names()`

## Evaluation
- **DBT**: `evaluation/comparator.py:evaluate()` — DuckDB table comparison using `_official_compare()`
  - Vector matching: transposes gold/pred DataFrames, checks each gold column vector matches ANY pred column
  - Numeric tolerance: 1e-2 (abs_tol)
  - Supports ignore_order (sorts both vectors)
  - Handles fct_↔fact_ prefix resolution
- **SQL**: `evaluation/sql_comparator.py:evaluate_sql()` — CSV comparison
  - Supports multiple gold variants ({id}_a.csv, {id}_b.csv)
  - Uses same `_official_compare()` from comparator.py

## Eval Integrity (eval firewall)
- `eval_config` (condition_tabs, condition_cols, gold DB path) is used ONLY by evaluation
- Agent prompt gets ONLY: task instruction + project files
- Post-agent fixes: ONLY generic dbt run, DuckDB WAL flush, connection cleanup
- VIOLATION patterns: selective dbt run using eval-critical models, name-fix agent that knows eval tables

## Known Integrity Issues in Current Code
- `runners/direct.py` loads `eval_critical_models` from eval config and uses them for:
  - `_run_dbt_selective()` — runs dbt on eval-critical models only (post-agent)
  - `_build_fix_prompt()` — includes eval-critical model names in fix prompt
  - `_run_name_fix_stage()` — dispatches agent to fix missing eval-critical tables
  - `create_sql_templates()` receives `_eval_critical_models` param (but doesn't use it for prioritization)
- These are post-agent steps, but they use eval config data — borderline per harness guide rules

## Key Paths
- BENCHMARK_DIR: `benchmark/`
- SKILLS_SRC: `benchmark/skills/`
- PROMPTS_DIR: `benchmark/prompts/`
- MCP_CONFIG: `benchmark/mcp_baked_config.json` (Docker) or `benchmark/mcp_config.json` (local)
- WORK_DIR: `benchmark/_dbt_workdir/` or env BENCHMARK_WORK_DIR
- SQL_WORK_DIR: `benchmark/_sql_workdir/`
- AUDIT_BASE: `/data/benchmark-audit` or env BENCHMARK_AUDIT_DIR

## Agent SDK Configuration
- Model: claude-sonnet-4-6 (default), claude-opus-4-6 for value-verify
- Max turns: 200 (DBT), 50 (SQL, auto-increased to 75 for large DBs)
- Permission mode: bypassPermissions
- Thinking: enabled, 20k budget
- System prompt: injected via sdk_runner
- MCP servers: loaded from mcp_config.json, env vars injected (SP_GATEWAY_URL, DATABASE_URL)
