# Spider2-DBT Benchmark

Automated benchmark pipeline for [Spider2-DBT](https://github.com/xlang-ai/Spider2) tasks using Claude Agent SDK + SignalPilot MCP.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  run4.sh (orchestrator)                                         │
│  - Launches 3 concurrent Docker containers                      │
│  - Polls for completion every 5s                                │
│  - Collects results immediately on exit                         │
│  - Fresh volume per task (zero stale data)                      │
│  - Per-task FAKETIME from gold_build_dates.json                 │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Container (sp-dbt-benchmark-agent)                              │
│  - python -m benchmark.run_direct <task>                        │
│  - Claude Agent SDK spawns agent + verifier subagent            │
│  - SignalPilot MCP (stdio) for governed DB access               │
│  - dbt wrapper: libfaketime for deterministic current_date      │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

### 1. Date Determinism

dbt models using `current_date` / `current_timestamp` produce different output depending on when they run. We solve this generically:

- **`derive_gold_dates.py`** — scans each gold DB to reverse-engineer when it was built (from calendar spines, age columns, or date boundaries). Produces `gold_build_dates.json`.
- **dbt wrapper** (`/usr/local/bin/dbt`) — applies `libfaketime` with the task's derived date for `run/compile/build` commands. Other commands (`deps`, `parse`) use the real clock for network access.
- **`FAKETIME_DONT_FAKE_MONOTONIC=1`** — prevents libfaketime from breaking Python's threading/multiprocessing.
- **`DO_NOT_TRACK=1` + `DBT_NO_VERSION_CHECK=1`** — disables dbt's outbound HTTPS calls that hang under faked time.

This is non-discriminate (same algorithm for all 64 tasks) and auditable (derivation script + JSON are checked in).

### 2. Agent Pipeline

For each task, the runner:

1. **Prepare workdir** — copies task from spider2 source, installs CLAUDE.md, registers MCP connection
2. **Snapshot reference tables** — captures pre-existing table row counts and column types
3. **Run agent** — Claude Agent SDK with system prompt, skills, and verifier subagent
4. **Evaluate** — compares result DB against gold using vector matching

### 3. Verification Subagent

After the main agent builds models, it spawns a verifier subagent that:

- Discovers all required models from YML (independent of main agent's message)
- Checks column schema, row counts, value spot-checks against reference snapshot
- Builds any missing models the main agent forgot
- Retries on DB lock errors (waits for dbt to release)

### 4. Evaluation

The comparator (`evaluation/comparator.py`) replicates Spider2's official `compare_pandas_table()`:

- Per-table vector matching with numeric tolerance (1e-2)
- Column-index-based comparison from eval config
- Supports `ignore_order` (sorts by sort key)
- Handles `fct_` ↔ `fact_` prefix resolution

## Running

### Prerequisites

- Docker Desktop
- Spider2-DBT dataset (examples + gold DBs)
- SignalPilot gateway running (`docker compose up gateway`)
- OAuth token in `.env`

### Single Task

```bash
# Inside container or with proper env:
python -m benchmark.run_direct chinook001 --model claude-sonnet-4-6
```

### Full Benchmark (64 tasks, 3 concurrent)

```bash
# Generate per-task dates (one-time or after gold changes)
python benchmark/derive_gold_dates.py

# Run all tasks
bash benchmark/run4.sh
```

Results stream to `benchmark/results/dbt-run4/run4.log`. Each task gets:
- `task_result.json` — pass/fail, turns, elapsed time
- `trace.json` — full agent transcript
- `project/` — workdir snapshot (SQL files, duckdb, dbt artifacts)
- `queries/` — MCP query audit log

### Re-run a Single Task

```bash
# With fresh volume and per-task date
TASK=shopify001
TASK_DATE=$(python3 -c "import json; print(json.load(open('benchmark/gold_build_dates.json'))['$TASK'])")
docker volume create sp-workdir-$TASK
docker run -d --name sp-run4-$TASK \
  -e FAKETIME="$TASK_DATE 12:00:00" \
  -e CLAUDE_CODE_OAUTH_TOKEN="$TOKEN" \
  ... sp-dbt-benchmark-agent -c "..."
```

## Directory Structure

```
benchmark/
├── run4.sh                      # Orchestrator script
├── run_direct.py                # Entry point (routes to runners/)
├── derive_gold_dates.py         # Derives per-task build dates from gold
├── gold_build_dates.json        # Cached per-task dates (auto-generated)
├── Dockerfile.dbt-agent         # Container image with dbt + faketime wrapper
├── mcp_test_config.json         # MCP server config for containers
│
├── runners/
│   └── direct.py                # Main benchmark runner
│
├── agent/
│   ├── prompts.py               # Agent prompt builder
│   └── sdk_runner.py            # Claude Agent SDK wrapper
│
├── prompts/
│   ├── dbt_local_system.md      # System prompt template
│   └── dbt_verify_subagent.md   # Verifier subagent prompt
│
├── skills/
│   ├── dbt-workflow/            # Project mapping, grain inference
│   ├── dbt-write/              # SQL writing rules, sibling patterns
│   ├── dbt-debugging/          # Error recovery
│   ├── dbt-date-spines/        # Date spine patterns
│   └── duckdb-sql/             # DuckDB syntax reference
│
├── core/
│   ├── suite.py                 # Suite config (task loading, skill lists)
│   ├── workdir.py               # Workdir lifecycle (prepare, CLAUDE.md)
│   ├── mcp.py                   # MCP connection management
│   ├── audit.py                 # Run result persistence
│   └── logging.py               # Logging utilities
│
├── evaluation/
│   ├── comparator.py            # Gold vs result comparison
│   └── db_utils.py             # DuckDB file utilities
│
├── dbt_tools/
│   ├── scanner.py               # Model classification (complete/stub/missing)
│   └── templates.py             # SQL template pre-population
│
└── results/
    └── dbt-run4/                # Current run results
        ├── run4.log             # Live progress log
        └── <task>/
            ├── task_result.json
            ├── trace.json
            ├── project/
            └── queries/
```

## Methodology

### Scoring

- **Task pass rate**: task passes if ALL eval tables pass
- **Table pass rate**: individual table pass/fail (more granular)
- A table passes if its value vectors match gold within tolerance

### Determinism

Sources of nondeterminism and how they're handled:

| Source | Mitigation |
|--------|-----------|
| `current_date` in SQL | libfaketime with per-task gold build date |
| Agent writes different SQL each run | Verifier subagent catches row count mismatches |
| dbt holds DB lock | Verifier retries on lock errors, 600s timeout |
| Stale workdir data | Fresh Docker volume per task |
| dbt telemetry hangs | `DO_NOT_TRACK=1`, `DBT_NO_VERSION_CHECK=1` |

### Eval Integrity

- No eval config data (condition_tabs, condition_cols) is exposed to the agent
- No post-agent fixes use eval-specific information
- The date derivation uses only gold DB contents (publicly available data)
- All prompts follow `benchmark-prompting.md` rules
