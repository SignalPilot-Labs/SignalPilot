"""Benchmark configuration — loads from .env and provides defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# SP_BENCHMARK_DIR controls where all heavy data lives (datasets, results, skills).
# Set it in .env to point at a drive with plenty of space, e.g.:
#   SP_BENCHMARK_DIR=D:\signalpilot-bench
# When unset, everything stays inside the repo's benchmark/ directory.
_BENCH_ROOT = os.getenv("SP_BENCHMARK_DIR", "")
BENCHMARK_DIR = Path(_BENCH_ROOT) if _BENCH_ROOT else Path(__file__).resolve().parent
DATASETS_DIR = BENCHMARK_DIR / "datasets"
RESULTS_DIR = BENCHMARK_DIR / "results"
SKILLS_DIR = BENCHMARK_DIR / "skills"

# Spider2 paths
SPIDER2_DIR = DATASETS_DIR / "spider2-lite"
SPIDER2_JSONL = SPIDER2_DIR / "spider2-lite.jsonl"
SPIDER2_GOLD_DIR = SPIDER2_DIR / "evaluation_suite" / "gold"
SPIDER2_GOLD_EXEC = SPIDER2_GOLD_DIR / "exec_result"
SPIDER2_GOLD_SQL = SPIDER2_GOLD_DIR / "sql"
SPIDER2_EVAL_CONFIG = SPIDER2_GOLD_DIR / "spider2lite_eval.jsonl"
SPIDER2_DATABASES_DIR = SPIDER2_DIR / "resource" / "databases" / "sqlite"
SPIDER2_DOCUMENTS_DIR = SPIDER2_DIR / "resource" / "documentation"

# Claude Agent SDK
CLAUDE_SETUP_TOKEN = os.getenv("CLAUDE_SETUP_TOKEN", "")

# SignalPilot MCP
SIGNALPILOT_MCP_CWD = str(PROJECT_ROOT / "signalpilot" / "gateway")
SIGNALPILOT_GATEWAY_URL = os.getenv("SP_GATEWAY_URL", "http://localhost:3300")


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark run."""
    # Which subset to run
    subset: str = "sqlite"  # sqlite | snowflake | bigquery | all
    # Limit number of tasks (0 = all)
    task_limit: int = 0
    # Specific instance IDs to run (empty = all matching subset)
    instance_ids: list[str] = field(default_factory=list)
    # Agent configuration
    model: str = "claude-sonnet-4-6"
    max_turns: int = 30
    max_budget_usd: float = 5.0
    timeout_per_task: int = 120  # seconds
    # Skills to load
    skills: list[str] = field(default_factory=list)
    # Run ID (auto-generated if empty)
    run_id: str = ""
    # Concurrency (how many tasks to run in parallel)
    concurrency: int = 1
    # Whether to use SignalPilot governance or direct SQL
    use_governance: bool = True
    # Row limit for queries
    row_limit: int = 1000
