# Spider2 Benchmark Suite with SignalPilot

Run [Spider2](https://github.com/xlang-ai/Spider2) benchmark tasks using Claude Agent SDK + SignalPilot MCP. Supports three benchmark suites:

| Suite | Tasks | Database | Agent Mode |
|-------|-------|----------|------------|
| **spider2-dbt** | dbt transformation projects | DuckDB | dbt project completion |
| **spider2-snowflake** | SQL questions against Snowflake | Snowflake (PAT) | SQL query writing |
| **spider2-lite** | SQL questions against multiple DBs | SQLite, BigQuery, Snowflake | SQL query writing |

The agent gets:
- Full Claude Code tool access (Read, Write, Edit, Bash, Glob, Grep, Agent, etc.)
- SignalPilot MCP server for governed database access (schema exploration, SQL queries)
- Suite-specific skills in `.claude/skills/`
- For dbt: dbt-duckdb for data transformation

## Quick Start

```bash
# 1. Setup (one-time per suite)
python -m benchmark.setup_dbt          # for spider2-dbt

# 2. Run a benchmark task
python -m benchmark.run_direct chinook001                              # dbt (default)
python -m benchmark.run_direct sf_task001 --suite spider2-snowflake    # snowflake
python -m benchmark.run_direct lite_task001 --suite spider2-lite       # lite
```

## Setup

### Common Prerequisites

```bash
# Set your OAuth token in .env at the SignalPilot repo root
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```

### Spider2-DBT Setup

```bash
# 1. Clone Spider2 and download data
git clone https://github.com/xlang-ai/Spider2.git ~/spider2-repo
cd ~/spider2-repo/spider2-dbt
pip install gdown
gdown 'https://drive.google.com/uc?id=1N3f7BSWC4foj-V-1C9n8M2XmgV7FOcqL'  # DBT_start_db.zip
gdown 'https://drive.google.com/uc?id=1s0USV_iQLo4oe05QqAMnhGGp5jeejCzp'  # dbt_gold.zip
python setup.py

# 2. Set env var (or add to .env)
export SPIDER2_DBT_DIR=~/spider2-repo/spider2-dbt

# 3. Run setup checks
python -m benchmark.setup_dbt
```

### Spider2-Snowflake Setup

```bash
# 1. Get spider2-snowflake data
# Set env var pointing to the data directory
export SPIDER2_SNOWFLAKE_DIR=~/spider2-repo/spider2-snowflake

# 2. Configure Snowflake credentials
# Create benchmark/.env.snowflake with:
SNOWFLAKE_ACCOUNT=<your-account>
SNOWFLAKE_USER=<your-user>
SNOWFLAKE_TOKEN=<your-programmatic-access-token>
SNOWFLAKE_ROLE=<your-role>
SNOWFLAKE_WAREHOUSE=<your-warehouse>
```

### Spider2-Lite Setup

```bash
# 1. Get spider2-lite data
export SPIDER2_LITE_DIR=~/spider2-repo/spider2-lite

# 2. For SQLite tasks: data is bundled in the dataset
# 3. For BigQuery tasks: place service_account.json in benchmark/
# 4. For Snowflake tasks: configure .env.snowflake (same as above)
```

### Credential Files (never commit these)

| File | Purpose | Required For |
|------|---------|--------------|
| `benchmark/.env.snowflake` | Snowflake PAT credentials | spider2-snowflake, spider2-lite (Snowflake tasks) |
| `benchmark/service_account.json` | BigQuery service account | spider2-lite (BigQuery tasks) |

These are covered by `benchmark/.gitignore`.

## Running Benchmarks

### Single Task

```bash
# spider2-dbt (default suite)
python -m benchmark.run_direct chinook001
python -m benchmark.run_direct chinook001 --model claude-opus-4-6
python -m benchmark.run_direct chinook001 --max-turns 30
python -m benchmark.run_direct chinook001 --skip-agent       # re-evaluate only
python -m benchmark.run_direct chinook001 --no-reset         # keep previous workdir

# spider2-snowflake
python -m benchmark.run_direct sf_task001 --suite spider2-snowflake
python -m benchmark.run_direct sf_task001 --suite spider2-snowflake --model claude-opus-4-6

# spider2-lite
python -m benchmark.run_direct lite_task001 --suite spider2-lite
```

### Batch Run

```bash
# Run all evaluable tasks for a suite
python -m benchmark.run_batch                                 # dbt (default)
python -m benchmark.run_batch --suite spider2-snowflake       # snowflake
python -m benchmark.run_batch --suite spider2-lite            # lite

# Limit to specific tasks
python -m benchmark.run_batch --tasks chinook001,f1001
python -m benchmark.run_batch --suite spider2-lite --tasks lite001,lite002
```

## How It Works

### Spider2-DBT Flow

1. Copies task dbt project + skills + `.mcp.json` to `_dbt_workdir/<id>`
2. Registers DuckDB with SignalPilot gateway
3. Runs main agent (writes SQL models, runs `dbt run`)
4. Post-agent safety nets: quick-fix, value-verify, name-fix agents
5. Evaluates: result DuckDB tables vs gold DuckDB tables
6. Cleans up connection

### Spider2-Snowflake / Spider2-Lite Flow

1. Creates clean workdir in `_sql_workdir/<suite>/<id>` with SQL skills
2. Registers appropriate connection (Snowflake PAT, SQLite file, or BigQuery service account)
3. Runs SQL agent (explores schema, writes query, executes via MCP, saves `result.csv`)
4. Evaluates: `result.csv` vs gold CSV
5. Cleans up connection

### Connection Registration Per Database

| Database | Method | Connection Fields |
|----------|--------|-------------------|
| DuckDB | Direct file path | `db_type=duckdb, database=<path>` |
| Snowflake | PAT (Programmatic Access Token) | `db_type=snowflake, account, user, password=<PAT>` |
| SQLite | File path | `db_type=sqlite, database=<path>` |
| BigQuery | Service account | `db_type=bigquery, project, dataset, credentials_json` |

### Credential Reload (Gateway Integration)

The benchmark runner registers connections via `gateway.store.create_connection()` before launching the agent. The MCP gateway process (started by Claude Agent SDK) picks up these credentials automatically via a **reload-on-miss** mechanism in `gateway/store.py`:

- `get_connection_string(name)` checks the in-memory vault first. If the key is missing, it re-reads `credentials.enc` from disk and retries.
- `get_credential_extras(name)` follows the same pattern for OAuth tokens, service account JSON, etc.
- This ensures externally registered connections are available without restarting the gateway.

### MCP Credential Extras (All Tools)

All MCP tool handlers in `gateway/mcp_server.py` pass `credential_extras` to the pool manager when acquiring connections. This ensures that BigQuery service account JSON and Snowflake PAT credentials flow through to the connectors for **every** tool — not just `query_database`. Without this, schema exploration tools (`list_tables`, `describe_table`, `schema_overview`, etc.) would fail for cloud databases because the connector falls back to default credentials (ADC / password auth).

### Validation Checks (every task must pass all 7)

1. **SDK connects to MCP** — agent runs without connection errors
2. **SDK sees skills** — skills copied to `.claude/skills/`, git init for discovery
3. **Correct system prompt** — suite-appropriate prompt with correct DB backend
4. **MCP connected to correct DB** — connection registered before agent, correct type
5. **No cross-task leakage** — connection deleted after each task, fresh registration
6. **Gold not leaked** — gold files live outside workdir, never copied in
7. **MCP query works** — actual SQL query executes through pool_manager with credential extras

## Architecture

```
benchmark/
├── run_direct.py          # entry point router (--suite flag)
├── run_batch.py           # batch runner (--suite flag)
│
├── core/                  # shared infrastructure
│   ├── suite.py           # BenchmarkSuite enum + SuiteConfig
│   ├── paths.py           # all path constants (DBT, Snowflake, Lite)
│   ├── tasks.py           # task/eval-config loaders (generic + suite-aware)
│   ├── workdir.py         # workdir setup (dbt + SQL variants)
│   ├── mcp.py             # connection registration (DuckDB, Snowflake, SQLite, BigQuery)
│   └── logging.py         # log() + log_separator()
│
├── runners/               # suite-specific orchestration
│   ├── direct.py          # spider2-dbt runner (dbt projects)
│   └── sql_runner.py      # spider2-snowflake + spider2-lite runner (SQL queries)
│
├── agent/                 # Claude Agent SDK glue
│   ├── sdk_runner.py      # run_sdk_agent wrapper (shared across all suites)
│   ├── prompts.py         # dbt-specific prompt builder
│   └── sql_prompts.py     # SQL-specific prompt builder (Snowflake/Lite)
│
├── evaluation/            # result comparison
│   ├── comparator.py      # DuckDB-vs-DuckDB (spider2-dbt)
│   ├── sql_comparator.py  # CSV-vs-CSV (spider2-snowflake, spider2-lite)
│   ├── db_utils.py        # find_result_db, row counts
│   └── local_comparator.py# positional comparator (legacy)
│
├── dbt_tools/             # dbt-specific analysis + fix-ups
│   ├── scanner.py, templates.py, fixes.py, postprocess.py
│
├── skills/                # Claude Code skills (copied per run)
│   ├── dbt-workflow/      # dbt project completion workflow
│   ├── dbt-verification/  # dbt output verification
│   ├── dbt-debugging/     # dbt error diagnosis
│   ├── dbt-date-spines/   # date spine patterns
│   ├── duckdb-sql/        # DuckDB SQL patterns
│   ├── sql-workflow/      # generic SQL workflow (Snowflake/Lite)
│   ├── snowflake-sql/     # Snowflake SQL patterns
│   ├── bigquery-sql/      # BigQuery SQL patterns
│   └── sqlite-sql/        # SQLite SQL patterns
│
├── prompts/               # prompt reference docs
│   ├── dbt_local_system.md
│   ├── sql_snowflake_system.md
│   └── sql_lite_system.md
│
├── validate_bench.py      # structural validation (per-suite, 6 checks)
├── validate_bench_e2e.py  # end-to-end validation (all suites, 30 checks)
│
├── legacy/                # older Spider2-SQLite flow (not imported by active runners)
└── docs/                  # supplementary notes
```

### Runtime Directories (not tracked in git)

- `_dbt_workdir/` — used by spider2-dbt runner
- `_sql_workdir/` — used by spider2-snowflake and spider2-lite runners
- `test-env/` — used by `run_dbt_local.py`

## Skills

Skills are suite-specific and copied to `.claude/skills/` in each task's workdir.

| Suite | Skills Loaded |
|-------|--------------|
| spider2-dbt | dbt-workflow, dbt-verification, dbt-debugging, duckdb-sql |
| spider2-snowflake | sql-workflow, snowflake-sql |
| spider2-lite | sql-workflow, snowflake-sql, bigquery-sql, sqlite-sql |

Add new skills by creating `benchmark/skills/<name>/SKILL.md` with frontmatter:

```markdown
---
description: Short description of what this skill does
---

## Skill content here
```

## Gold Data

### Spider2-DBT Gold

Out of 68 total tasks, 60 have correct gold data, 7 have no gold DB file, and 1 has a table name mismatch.

```bash
python -m benchmark.setup_dbt --audit           # audit gold data
python -m benchmark.setup_dbt --build-gold       # build missing gold DBs
```

### Spider2-Snowflake / Lite Gold

Gold results are CSV files in the evaluation suite. The evaluator compares the agent's `result.csv` against gold CSVs using the same vector-matching algorithm as the dbt evaluator.

## Validation

Two validation scripts verify the benchmark infrastructure before running real tasks.

### Structural Validation (per-suite)

```bash
python -m benchmark.validate_bench --suite spider2-lite
python -m benchmark.validate_bench --suite spider2-snowflake
python -m benchmark.validate_bench --suite spider2-dbt
```

Runs 6 structural checks per suite: workdir creation, MCP config, skills discovery, system prompt, connection registration, and gold leak prevention. Exits 0 if all pass/skip, 1 if any fail.

### End-to-End Validation (all suites at once)

```bash
python -m benchmark.validate_bench_e2e
python -m benchmark.validate_bench_e2e --verbose
```

Runs 5 synthetic tasks across all 3 suites and all 4 database backends (35 total checks):

| Task | Suite | DB Backend | What it tests |
|------|-------|------------|---------------|
| 1 | spider2-snowflake | Snowflake | PAT connection via `.env.snowflake` |
| 2 | spider2-dbt | DuckDB | Local DuckDB file + dbt skills + dbt system prompt |
| 3 | spider2-lite | SQLite | Local SQLite file + SQL skills |
| 4 | spider2-lite | Snowflake | Snowflake connection via lite suite |
| 5 | spider2-lite | BigQuery | BigQuery via `service_account.json` |

Each task runs 7 checks:

| # | Check | What it verifies |
|---|-------|-----------------|
| 1 | **workdir_setup** | Directory created with `.mcp.json`, `.git/`, correct structure |
| 2 | **skills_copied** | Suite-specific `SKILL.md` files present in `.claude/skills/` |
| 3 | **system_prompt** | Correct prompt file exists; template variables resolve cleanly |
| 4 | **connection_registered** | DB connection in gateway store with correct `db_type` |
| 5 | **no_bloat** | No leftover `e2e_validate_*` connections from prior tasks |
| 6 | **no_gold_leak** | No gold-related files in the workdir |
| 7 | **mcp_query** | Actual SQL query executes through pool_manager with credential extras |

Snowflake/BigQuery checks SKIP (not FAIL) if credential files are absent or cloud auth fails (credential issue, not code bug). All cleanup (workdirs, connections, temp DB files) runs in `finally` blocks.

### Quick Verification Sequence

```bash
# Run both validations to confirm everything works:
python -m benchmark.validate_bench --suite spider2-dbt
python -m benchmark.validate_bench --suite spider2-snowflake
python -m benchmark.validate_bench --suite spider2-lite
python -m benchmark.validate_bench_e2e
```

## System Prompts

### Generalized System Prompt (`prompts/system_general.md`)

SQL suites (spider2-snowflake, spider2-lite) receive a generalized system prompt injected via the Claude Agent SDK. The prompt:

- Describes all SignalPilot MCP tools generically (no hardcoded database names)
- Uses template variables `${work_dir}`, `${instance_id}`, `${connection_name}` filled at runtime
- Lists dbt tools as conditionally available
- Keeps the agent focused: explore schema → write query → verify → save `result.csv`

The dbt suite continues to use its own `prompts/dbt_local_system.md` (unchanged).

## Environment Variables

| Variable | Required For | Description |
|----------|-------------|-------------|
| `CLAUDE_CODE_OAUTH_TOKEN` | All suites | Claude Code OAuth token |
| `SPIDER2_DBT_DIR` | spider2-dbt | Path to spider2-dbt data directory |
| `SPIDER2_SNOWFLAKE_DIR` | spider2-snowflake | Path to spider2-snowflake data directory |
| `SPIDER2_LITE_DIR` | spider2-lite | Path to spider2-lite data directory |
| `SP_GATEWAY_URL` | All suites | SignalPilot gateway URL (default: http://localhost:3300) |
