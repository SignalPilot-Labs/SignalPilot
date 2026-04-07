# Spider2-DBT Benchmark with SignalPilot

Run Spider2-DBT benchmark tasks inside a Docker container using Claude Agent SDK + SignalPilot MCP.

The agent gets:
- Full Claude Code tool access (Read, Write, Edit, Bash, Glob, Grep, Agent, etc.)
- SignalPilot MCP server for governed database access (schema exploration, SQL queries)
- Benchmark skills in `.claude/skills/` (dbt, DuckDB, SQL, SignalPilot)
- dbt-duckdb for data transformation

## Prerequisites

- Docker Desktop
- Python 3.11+ with conda/venv
- Claude Code subscription (OAuth token)
- ~5 GB disk for Spider2 datasets

## Setup

### 1. Clone Spider2

```bash
git clone https://github.com/xlang-ai/Spider2.git ~/spider2-repo
cd ~/spider2-repo/spider2-dbt

# Download DuckDB databases
pip install gdown
gdown 'https://drive.google.com/uc?id=1N3f7BSWC4foj-V-1C9n8M2XmgV7FOcqL'  # DBT_start_db.zip
gdown 'https://drive.google.com/uc?id=1s0USV_iQLo4oe05QqAMnhGGp5jeejCzp'  # dbt_gold.zip

# Extract databases into task directories
python setup.py
```

### 2. Set paths

Edit `benchmark/run_dbt_single.py` and update the paths at the top:

```python
SPIDER2_DBT_DIR = Path("~/spider2-repo/spider2-dbt")  # where you cloned Spider2
WORK_DIR = Path("~/SignalPilot/benchmark/_dbt_workdir")
GATEWAY_SRC = Path("~/SignalPilot/signalpilot/gateway")
```

### 3. Set your OAuth token

Add to `.env` in the SignalPilot repo root:

```
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```

Get this from `~/.claude/.credentials.json` → `claudeAiOauth.accessToken`, or from the Claude Code CLI settings.

### 4. Start SignalPilot gateway

```bash
cd signalpilot
docker compose -f docker/docker-compose.dev.yml up -d
```

Verify it's running:
```bash
curl http://localhost:3300/api/connections
# Should return []
```

### 5. Build the benchmark Docker image

```bash
cd benchmark
docker build -t sp-dbt-benchmark-agent -f Dockerfile.dbt-agent .
```

### 6. Install Python deps (host)

```bash
pip install python-dotenv duckdb pandas
```

## Running a benchmark

### Single task

```bash
python -m benchmark.run_dbt_single chinook001
```

Options:
```
python -m benchmark.run_dbt_single <instance_id> [options]

  --model MODEL        Claude model (default: claude-opus-4-6)
  --max-turns N        Max agent turns (default: 30)
  --budget AMOUNT      Max USD budget (default: 5.0)
  --skip-build         Skip Docker image rebuild
  --skip-agent         Skip agent run, just evaluate existing results
```

### What happens

1. **Setup** — Copies task dbt project + skills to a working directory
2. **SignalPilot** — Clears all DB connections, registers only the task's DuckDB
3. **Docker** — Creates container, copies workspace in, mounts gateway source
4. **Agent** — Claude Agent SDK runs inside the container with full tools + SignalPilot MCP
5. **dbt run** — Agent writes missing SQL models, runs `dbt deps && dbt run`
6. **Copy back** — Results copied from container to host
7. **Evaluate** — Compares result DuckDB tables against gold standard

### Output

```
============================================================
Spider2-DBT E2E Benchmark - chinook001
============================================================
  [setup] Copied 6 skills to .claude/skills
  SignalPilot: clean slate, 1 connection registered
  Agent: 15 turns, 90s, 17/17 dbt models PASS
  Eval: dim_customer PASS, obt_invoice PASS
============================================================
RESULT: PASS
============================================================
```

Agent results are saved to `benchmark/_dbt_workdir/<instance_id>/agent_result.json`.

## Architecture

```
Host                              Docker Container
────────────────────              ─────────────────────────────
                                  sp-dbt-benchmark-agent
run_dbt_single.py                 ┌─────────────────────────┐
  │                               │ dbt_agent_runner.py      │
  │ docker create/cp/start        │   │                      │
  ├──────────────────────────────►│   ├─ Claude Agent SDK    │
  │                               │   │    └─ Claude CLI     │
  │                               │   │         ├─ Read/Write│
  │                               │   │         ├─ Bash      │
  │                               │   │         └─ MCP ──────┤
  │                               │   │              │       │
  │                               │   │    SignalPilot MCP   │
  │                               │   │    (stdio server)    │
  │                               │   │         │            │
SignalPilot Gateway ◄─────────────┤   │    query_database    │
(port 3300)                       │   │    list_tables        │
  │                               │   │    describe_table    │
  │                               │   │    explore_table     │
  │ DuckDB connection             │   │    ...               │
  │ registered via API            │   │                      │
  │                               │ /workspace/              │
  │                               │   ├─ chinook.duckdb      │
  │ docker cp results ◄──────────│   ├─ models/             │
  │                               │   ├─ .claude/skills/     │
  │ evaluate()                    │   └─ dbt_project.yml     │
  │   gold DB vs result DB        └─────────────────────────┘
```

## Skills

Skills live in `benchmark/skills/` and are copied to `.claude/skills/` in the container.
Claude Code discovers and loads them automatically.

```
benchmark/skills/
├── dbt/
│   ├── expert/SKILL.md         — YAML-to-SQL workflow, naming, dbt syntax
│   └── debugging/SKILL.md      — Error types, fix strategies, common mistakes
├── duckdb/
│   ├── patterns/SKILL.md       — String, aggregation, window, type casting
│   └── date-time/SKILL.md      — Date arithmetic, formatting, PG/MySQL diffs
├── signalpilot/
│   └── data-tools/SKILL.md     — MCP tools for schema discovery and queries
└── sql/
    └── query-building/SKILL.md — CTEs, joins, validation, exploration
```

Add new skills by creating a directory with a `SKILL.md` file:
```bash
mkdir -p benchmark/skills/sqlite/patterns
cat > benchmark/skills/sqlite/patterns/SKILL.md << 'EOF'
---
description: "SQLite-specific patterns and functions."
---
# SQLite Patterns
...
EOF
```

## SignalPilot MCP Tools

The agent has access to 25 SignalPilot tools including:

| Tool | Purpose |
|------|---------|
| `query_database` | Execute governed read-only SQL |
| `list_database_connections` | See registered databases |
| `list_tables` | Table names + schema overview |
| `describe_table` | Column details for a table |
| `explore_table` | Deep-dive with sample values |
| `schema_overview` | Quick DB stats |
| `find_join_path` | FK-based join path between tables |
| `validate_sql` | Check SQL without executing |

All queries go through SignalPilot governance (read-only enforcement, LIMIT injection, audit logging).

## Available Tasks

Spider2-DBT has 69 DuckDB transformation tasks. List them:
```bash
python -c "
import json
with open('path/to/spider2-dbt/examples/spider2-dbt.jsonl') as f:
    for line in f:
        t = json.loads(line)
        print(f\"{t['instance_id']:30s} {t['instruction'][:80]}\")
"
```

Start with `chinook001` (simplest), then try others like `formula1001`, `retail001`, etc.
