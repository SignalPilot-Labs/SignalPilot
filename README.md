# SignalPilot

AI-powered data engineering agent with governed database access, benchmarked on Spider 2.0.

## Components

| Directory | Description |
|-----------|-------------|
| `signalpilot/` | Core gateway + web UI — governed MCP server for AI database access |
| `benchmark/` | Spider 2.0 benchmark suite (DBT, Snowflake, Lite) with Claude Agent SDK |
| `sp-firecracker-vm/` | Firecracker/gVisor sandboxed code execution |
| `testing/` | Data generation and integration test infrastructure |

---

## Benchmark

Run Spider 2.0 tasks using the Claude Agent SDK with SignalPilot MCP tools for schema discovery, SQL execution, and dbt project management.

### Supported Suites

| Suite | Backend | Tasks |
|-------|---------|-------|
| `spider2-dbt` | DuckDB (local) | 65 dbt projects |
| `spider2-snowflake` | Snowflake | SQL generation |
| `spider2-lite` | SQLite, BigQuery, Snowflake | SQL generation |

### Running Benchmarks

```bash
# Single task (individual runner)
python -m benchmark.run_direct chinook001
python -m benchmark.run_direct --suite spider2-snowflake sf_local041

# Batch (sequential)
python -m benchmark.run_batch --suite spider2-dbt --model claude-sonnet-4-6

# Batch (parallel, 4 concurrent)
python -m benchmark.run_batch --suite spider2-dbt --parallel 4

# Specific tasks
python -m benchmark.run_batch --suite spider2-dbt --tasks chinook001 f1001 shopify001

# Evaluate only (skip agent, re-score existing results)
python -m benchmark.run_batch --suite spider2-dbt --eval-only
```

### Docker

```bash
# Build the benchmark agent image
docker build -f benchmark/Dockerfile.dbt-agent -t signalpilot/dbt-agent .

# Run with audit volume
docker run \
  -v sp-benchmark-audit:/data/benchmark-audit \
  -e ANTHROPIC_API_KEY=... \
  signalpilot/dbt-agent chinook001
```

The audit volume must be mounted at `/data/benchmark-audit` (or set `BENCHMARK_AUDIT_DIR`).

---

## Audit Volume (`sp-benchmark-audit`)

Every benchmark run — whether via `run_batch.py` (batch) or individual runners — persists a full audit trail to the `sp-benchmark-audit` Docker volume.

### Directory Structure

```
/data/benchmark-audit/
├── runs/
│   ├── {run_id}/                          # Batch: UUID, Individual: single-{id}-{timestamp}
│   │   ├── run_metadata.json              # Suite, model, timestamps, concurrency, pass count
│   │   ├── tasks/
│   │   │   └── {instance_id}.json         # Per-task result: passed, elapsed, turns, cost, usage
│   │   ├── traces/
│   │   │   └── {instance_id}.json         # Full conversation transcript (see below)
│   │   ├── queries/
│   │   │   └── {instance_id}.jsonl        # Gateway SQL audit entries for this task
│   │   ├── logs/
│   │   │   └── {instance_id}.log          # Console output (parallel mode)
│   │   └── projects/
│   │       └── {instance_id}/             # Agent-generated work products
│   │           ├── models/*.sql           # SQL models the agent wrote
│   │           ├── *.duckdb               # Output database (evaluation target)
│   │           ├── dbt_project.yml        # Project config
│   │           ├── result.csv / result.sql # Query results
│   │           └── agent_output.json      # Local transcript copy
│   └── ...
└── submissions/
    └── submission_{run_id}.tar.gz         # Packaged archive for leaderboard
```

### Transcript Format

Each `traces/{instance_id}.json` contains a chronologically ordered `transcript` array. Every entry has `type`, `turn`, and `timestamp` (Unix epoch). Event types:

| Type | Description | Key Fields |
|------|-------------|------------|
| `thinking` | Agent's internal reasoning | `content` |
| `text` | Agent's visible output | `content` |
| `tool_use` | Tool invocation | `name`, `input` |
| `tool_result` | Tool execution result | `content`, `tool_use_id`, `is_error` |
| `tool_use_result` | Structured result dict | `content` |
| `user_message` | User-side content | `content` |
| `system` | System events (init, config) | `subtype`, `data` |
| `result` | Run completion summary | `total_cost_usd`, `duration_ms`, `stop_reason`, `usage` |
| `rate_limit` | Rate limit warnings | `info` |
| `stream_event` | Low-level SDK events | `event` |

### Task Result Format (`tasks/{instance_id}.json`)

```json
{
  "instance_id": "chinook001",
  "run_id": "single-chinook001-1776204010",
  "suite": "spider2-dbt",
  "passed": true,
  "elapsed_seconds": 142.5,
  "turns": 27,
  "tool_call_count": 14,
  "cost_usd": 0.42,
  "usage": { "input_tokens": 50000, "output_tokens": 12000 },
  "model": "claude-sonnet-4-6",
  "error": null,
  "timestamps": { "total": 142.5 },
  "agent_transcript_path": "traces/chinook001.json"
}
```

---

## Spider 2.0 Submission

### Packaging

After a benchmark run completes:

```bash
python -m benchmark.package_submission --run-id <run_id>
```

This creates `submissions/submission_{run_id}.tar.gz` containing:
- `run_metadata.json` — run-level info (model, suite, timestamps)
- `scores.json` — `{instance_id: {passed, elapsed}}` for all tasks
- `results/{instance_id}.json` — per-task details
- `traces/{instance_id}.json` — full reasoning traces with timestamps
- `queries/{instance_id}.jsonl` — SQL audit trail from gateway
- `projects/{instance_id}/` — agent work products (models, output DBs)
- `logs/{instance_id}.log` — console output

### Submission Guidelines

Per the [Spider 2.0 evaluation rules](https://spider2-sql.github.io/):

- **One result per task** — enforced by immutable result storage (`ResultAlreadyExistsError`)
- **Timestamped logs** — every transcript event has a Unix timestamp
- **Reasoning traces** — full thinking + tool use + tool results chain
- **No cherry-picking** — if running multiple experiments, the agent must autonomously select the final result (e.g., majority voting)

Submit the archive and a method description to `lfy79001@gmail.com`.

### Suites

| Suite | What to Submit | Gold Format |
|-------|----------------|-------------|
| Spider 2.0-DBT | Log files + scores | DuckDB tables vs gold DuckDB |
| Spider 2.0-Lite | `{id}.sql` + `{id}.csv` + traces | CSV comparison |
| Spider 2.0-Snow | `{id}.sql` + `{id}.csv` + traces | CSV comparison |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | API key for Claude |
| `BENCHMARK_AUDIT_DIR` | `/data/benchmark-audit` | Audit storage path (mount Docker volume here) |
| `SP_GATEWAY_URL` | `http://localhost:3300` | SignalPilot gateway URL |
| `SPIDER2_DBT_DIR` | `~/spider2-repo/spider2-dbt` | Path to Spider 2.0-DBT dataset |
| `SPIDER2_SNOWFLAKE_DIR` | `~/spider2-repo/spider2-snow` | Path to Spider 2.0-Snow dataset |
| `SPIDER2_LITE_DIR` | `~/spider2-repo/spider2-lite` | Path to Spider 2.0-Lite dataset |

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
