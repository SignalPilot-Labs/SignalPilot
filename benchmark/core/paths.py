"""Filesystem paths shared across the dbt benchmark runners."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root so SPIDER2_DBT_DIR and friends are available.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

BENCHMARK_DIR = Path(__file__).resolve().parent.parent

SPIDER2_DBT_DIR = Path(
    os.environ.get("SPIDER2_DBT_DIR", os.path.expanduser("~/spider2-repo/spider2-dbt"))
)
EXAMPLES_DIR = SPIDER2_DBT_DIR / "examples"
GOLD_DIR = SPIDER2_DBT_DIR / "evaluation_suite" / "gold"
EVAL_JSONL = GOLD_DIR / "spider2_eval.jsonl"
TASK_JSONL = EXAMPLES_DIR / "spider2-dbt.jsonl"

SPIDER2_SNOWFLAKE_DIR = Path(
    os.environ.get("SPIDER2_SNOWFLAKE_DIR", os.path.expanduser("~/spider2-repo/spider2-snow"))
)
SPIDER2_LITE_DIR = Path(
    os.environ.get("SPIDER2_LITE_DIR", os.path.expanduser("~/spider2-repo/spider2-lite"))
)
SQL_WORK_DIR = BENCHMARK_DIR / "_sql_workdir"
SNOWFLAKE_ENV_FILE = PROJECT_ROOT / ".env"
BIGQUERY_SA_FILE = PROJECT_ROOT / "gcp-service-account.json"

WORK_DIR = Path(os.environ.get("BENCHMARK_WORK_DIR", str(BENCHMARK_DIR / "_dbt_workdir")))
TEST_ENV = BENCHMARK_DIR / "test-env"
SKILLS_SRC = BENCHMARK_DIR / "skills"
PROMPTS_DIR = BENCHMARK_DIR / "prompts"
GATEWAY_SRC = PROJECT_ROOT / "signalpilot" / "gateway"
MCP_CONFIG = BENCHMARK_DIR / "mcp_test_config.json"
GATEWAY_URL = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")


AUDIT_BASE = Path(os.environ.get("BENCHMARK_AUDIT_DIR", "/data/benchmark-audit"))
# Note: if running in Docker, mount the sp-benchmark-audit volume at /data/benchmark-audit.
# The Python code does not create Docker volumes.


def ensure_local_bin_on_path() -> None:
    """Ensure pip-installed CLIs (like dbt) are on PATH for subprocess children."""
    local_bin = os.path.expanduser("~/.local/bin")
    if local_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = local_bin + os.pathsep + os.environ.get("PATH", "")
