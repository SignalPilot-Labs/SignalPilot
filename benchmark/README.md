# Spider2-DBT Benchmark with SignalPilot

Run [Spider2-DBT](https://github.com/xlang-ai/Spider2) benchmark tasks using Claude Agent SDK + SignalPilot MCP. Two modes: **local** (no Docker) and **Docker** (isolated container).

The agent gets:
- Full Claude Code tool access (Read, Write, Edit, Bash, Glob, Grep, Agent, etc.)
- SignalPilot MCP server for governed database access (schema exploration, SQL queries)
- Benchmark skills in `.claude/skills/` (dbt, DuckDB, SQL, SignalPilot)
- dbt-duckdb for data transformation

## Quick Start (Local)

```bash
# 1. Setup (one-time)
python -m benchmark.setup_dbt

# 2. Start SignalPilot gateway
cd signalpilot && docker compose -f docker/docker-compose.dev.yml up -d

# 3. Run a benchmark
python -m benchmark.run_dbt_local chinook001
```

## Setup

### 1. Clone Spider2 and download data

```bash
git clone https://github.com/xlang-ai/Spider2.git ~/spider2-repo
cd ~/spider2-repo/spider2-dbt
pip install gdown
gdown 'https://drive.google.com/uc?id=1N3f7BSWC4foj-V-1C9n8M2XmgV7FOcqL'  # DBT_start_db.zip
gdown 'https://drive.google.com/uc?id=1s0USV_iQLo4oe05QqAMnhGGp5jeejCzp'  # dbt_gold.zip
python setup.py
```

### 2. Set your OAuth token

Add to `.env` in the SignalPilot repo root:

```
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```

Get from `~/.claude/.credentials.json` -> `claudeAiOauth.accessToken`.

### 3. Run the setup script

```bash
python -m benchmark.setup_dbt
```

This checks/installs Python deps, verifies Spider2 data, audits gold DBs, and reports any issues.

### 4. Start SignalPilot gateway

```bash
cd signalpilot
docker compose -f docker/docker-compose.dev.yml up -d
curl http://localhost:3300/api/connections  # should return []
```

## Running Benchmarks

### Direct runner (recommended for benchmarking)

The fastest runner. Uses Claude CLI directly with SignalPilot MCP. Works in `benchmark/_dbt_workdir/<instance_id>`.

```bash
# Run a single task
CLAUDE_CODE_OAUTH_TOKEN=<token> python benchmark/run_direct.py chinook001

# Options
python benchmark/run_direct.py chinook001 --model claude-sonnet-4-6  # default model
python benchmark/run_direct.py chinook001 --model claude-opus-4-6    # for harder tasks
python benchmark/run_direct.py chinook001 --max-turns 30             # more turns
python benchmark/run_direct.py chinook001 --skip-agent               # just eval existing results
python benchmark/run_direct.py chinook001 --no-reset                 # keep previous workdir
```

**How it works:**
1. Copies task dbt project + skills + `.mcp.json` to workdir
2. Registers DuckDB with SignalPilot gateway
3. Runs main agent (Claude CLI with MCP tools)
4. Runs quick-fix agent if dbt build fails
5. Runs value-verification agent
6. Runs name-fix agent if eval-critical tables are missing
7. Evaluates against gold standard
8. Cleans up SignalPilot connection

### Local runner

No Docker required. Runs the agent directly on the host in `benchmark/test-env/<instance_id>`. Each run gets a clean workspace.

```bash
python -m benchmark.run_dbt_local chinook001
python -m benchmark.run_dbt_local chinook001 --model claude-sonnet-4-6
python -m benchmark.run_dbt_local chinook001 --max-turns 15 --budget 2.0
python -m benchmark.run_dbt_local chinook001 --no-mcp        # disable SignalPilot MCP
python -m benchmark.run_dbt_local chinook001 --skip-agent     # just eval existing results
python -m benchmark.run_dbt_local chinook001 --adopt-gold     # adopt result as new gold DB
```

### Docker runner

Full isolation. Requires building the Docker image first.

```bash
# Build image (one-time)
docker build -t sp-dbt-benchmark-agent -f benchmark/Dockerfile.dbt-agent benchmark/

# Run
python -m benchmark.run_dbt_single chinook001
python -m benchmark.run_dbt_single chinook001 --skip-build    # skip image rebuild
```

### What happens

1. **Clean workspace** — Copies task dbt project + skills to `test-env/<id>` (local) or container (Docker)
2. **SignalPilot setup** — Clears all DB connections, registers only the task's DuckDB
3. **Agent runs** — Claude Agent SDK with full tools + SignalPilot MCP
4. **dbt run** — Agent writes missing SQL models, runs `dbt deps && dbt run`
5. **Evaluate** — Compares result DuckDB tables against gold standard

## Gold Data

### The problem

Spider2's `dbt_gold.zip` has known issues:

| Issue | Tasks affected | Description |
|-------|---------------|-------------|
| Missing gold DB | 7 tasks (xero_new001, airbnb002, biketheft001, google_ads001, social_media001, xero_new002, gitcoin001) | No gold DuckDB file in the zip at all |
| Naming mismatch | chinook001 | Eval config expects `fct_invoice` but YAML defines `fact_invoice` |

Out of 68 total tasks, **60 have correct gold data**, 7 have no gold DB file, and 1 has a table name mismatch in the eval config.

### Auditing gold data

```bash
python -m benchmark.setup_dbt --audit
```

### Building missing gold DBs

For tasks where gold DBs are missing, you can build them by running dbt on the example project (only works if the example already has all SQL models):

```bash
python -m benchmark.setup_dbt --build-gold              # build all missing
python -m benchmark.setup_dbt --build-gold chinook001    # build specific task
```

### Adopting agent results as gold

After a successful benchmark run, you can adopt the result as the gold standard:

```bash
# Run the benchmark
python -m benchmark.run_dbt_local chinook001

# If it passes dbt run, adopt as gold
python -m benchmark.run_dbt_local chinook001 --skip-agent --adopt-gold

# Or manually:
python -m benchmark.setup_dbt --adopt-result chinook001 benchmark/test-env/chinook001
```

This is useful for bootstrapping gold data for tasks where the Spider2 zip is incomplete.

## Architecture

```
Host
  run_dbt_local.py  (or run_dbt_single.py for Docker)
    |
    +-- prepare_test_env()    copy task project + .claude/skills/ to test-env/
    +-- setup_signalpilot()   clear connections, register task DuckDB
    +-- run_agent()           Claude Agent SDK with MCP
    |     |
    |     +-- Claude Code CLI
    |     |     +-- Read, Write, Edit, Bash, Glob, Grep
    |     |     +-- SignalPilot MCP (stdio subprocess)
    |     |           +-- query_database (governed SQL)
    |     |           +-- list_tables, describe_table, explore_table
    |     |           +-- find_join_path, schema_overview
    |     |
    |     +-- /signalpilot/gateway/  (MCP server source)
    |
    +-- SignalPilot Gateway (port 3300)
    |     +-- DuckDB connection registered
    |     +-- Governance pipeline (read-only, LIMIT injection, audit)
    |
    +-- run_dbt()             final dbt deps + dbt run validation
    +-- evaluate()            compare result DB vs gold DB
```

## Skills

Skills live in `benchmark/skills/` and are copied to `.claude/skills/` in the workspace. Claude Code discovers and loads them automatically.

```
benchmark/skills/
+-- dbt/
|   +-- expert/SKILL.md         YAML-to-SQL workflow, naming, dbt syntax
|   +-- debugging/SKILL.md      Error types, fix strategies, common mistakes
+-- duckdb/
|   +-- patterns/SKILL.md       String, aggregation, window, type casting
|   +-- date-time/SKILL.md      Date arithmetic, formatting, PG/MySQL diffs
+-- signalpilot/
|   +-- data-tools/SKILL.md     MCP tools for schema discovery and queries
+-- sql/
    +-- query-building/SKILL.md CTEs, joins, validation, exploration
```

Add new skills by creating a directory with a `SKILL.md`:
```bash
mkdir -p benchmark/skills/sqlite/patterns
# Write SKILL.md with --- frontmatter (description field) + content
```

## Available Tasks

Spider2-DBT has 68 DuckDB transformation tasks. List them:
```bash
python -c "
import json
with open('path/to/spider2-dbt/examples/spider2-dbt.jsonl') as f:
    for line in f:
        t = json.loads(line)
        print(f\"{t['instance_id']:30s} {t['instruction'][:80]}\")
"
```

Start with `chinook001` (simplest), then try `f1001`, `playbook001`, `shopify001`, etc.
