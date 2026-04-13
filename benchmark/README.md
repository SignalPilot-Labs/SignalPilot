# Spider2 Benchmark Suite with SignalPilot

Run [Spider2](https://github.com/xlang-ai/Spider2) benchmark tasks using Claude Agent SDK + SignalPilot MCP. Supports three benchmark suites:

| Suite | Tasks | Database | Agent Mode |
|-------|-------|----------|------------|
| **spider2-dbt** | dbt transformation projects | DuckDB | dbt project completion |
| **spider2-snowflake** | SQL questions against Snowflake | Snowflake (OAuth) | SQL query writing |
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
SNOWFLAKE_TOKEN=<your-oauth-token>
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
| `benchmark/.env.snowflake` | Snowflake OAuth credentials | spider2-snowflake, spider2-lite (Snowflake tasks) |
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
2. Registers appropriate connection (Snowflake OAuth, SQLite file, or BigQuery service account)
3. Runs SQL agent (explores schema, writes query, executes via MCP, saves `result.csv`)
4. Evaluates: `result.csv` vs gold CSV
5. Cleans up connection

### Connection Registration Per Database

| Database | Method | Connection Fields |
|----------|--------|-------------------|
| DuckDB | Direct file path | `db_type=duckdb, database=<path>` |
| Snowflake | OAuth token | `db_type=snowflake, account, user, token` + OAuth extras |
| SQLite | File path | `db_type=sqlite, database=<path>` |
| BigQuery | Service account | `db_type=bigquery, project, dataset, credentials_json` |

### Validation Checks (every task must pass all 6)

1. **SDK connects to MCP** — agent runs without connection errors
2. **SDK sees skills** — skills copied to `.claude/skills/`, git init for discovery
3. **Correct system prompt** — suite-appropriate prompt with correct DB backend
4. **MCP connected to correct DB** — connection registered before agent, correct type
5. **No cross-task leakage** — connection deleted after each task, fresh registration
6. **Gold not leaked** — gold files live outside workdir, never copied in

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
│   └── bigquery-sql/      # BigQuery SQL patterns
│
├── prompts/               # prompt reference docs
│   ├── dbt_local_system.md
│   ├── sql_snowflake_system.md
│   └── sql_lite_system.md
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

Before running the full benchmark, use the validation script to verify that all infrastructure components are working correctly for a given suite.

### Running Validation

```bash
# Validate spider2-lite (fastest — no Snowflake required)
python -m benchmark.validate_bench --suite spider2-lite

# Validate spider2-snowflake (requires .env.snowflake)
python -m benchmark.validate_bench --suite spider2-snowflake

# Validate spider2-dbt (requires spider2-dbt data directory)
python -m benchmark.validate_bench --suite spider2-dbt
```

Exits 0 if all checks pass or skip, 1 if any check fails.

### What the 6 Checks Verify

| # | Check | What it verifies |
|---|-------|-----------------|
| 1 | **workdir_creation** | Creates a synthetic task workdir; verifies `.mcp.json`, `.git`, and skills are in place |
| 2 | **mcp_config** | Loads `mcp_test_config.json`; verifies `signalpilot` key with `command` and `args` |
| 3 | **skills_discoverable** | Verifies every skill in `config.skills` has a `SKILL.md` under `benchmark/skills/` |
| 4 | **system_prompt** | SQL suites: verifies `system_general.md` exists and has no hardcoded DB names. DBT: verifies `dbt_local_system.md` mentions dbt |
| 5 | **connection_registration** | Registers a test connection per backend type, verifies it appears in the gateway store, then deletes it. Skips if credential files are absent |
| 6 | **no_gold_leak** | Prepares a workdir and checks that no gold filenames appear in it. Skipped if spider2 data is not downloaded |

### Graceful Handling

- Checks that need spider2 data dirs (`check_1`, `check_6`) emit `SKIP` (not `FAIL`) if the data has not been downloaded.
- Checks that need credential files (`check_5`) emit `SKIP` if `.env.snowflake` or `service_account.json` is absent.
- All cleanup (workdirs, registered connections) runs in `finally` blocks.

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
