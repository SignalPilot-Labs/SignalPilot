"""Spider2 SQL benchmark runner — handles spider2-snowflake and spider2-lite suites.

Mirrors the structure of runners/direct.py but without dbt dependencies.
The agent writes its result as result.csv and result.sql in the workdir.

Usage:
    python -m benchmark.run_direct --suite spider2-snowflake sf_tpch001
    python -m benchmark.run_direct --suite spider2-lite lite_sqlite001
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from ..agent.sdk_runner import run_sdk_agent
from ..agent.sql_prompts import build_sql_agent_prompt
from ..core.logging import log, log_separator
from ..core.mcp import (
    delete_local_connection,
    register_bigquery_connection,
    register_snowflake_connection,
    register_sqlite_connection,
    _load_dotenv_file,
)
from ..core.paths import SNOWFLAKE_ENV_FILE
from ..core.paths import PROMPTS_DIR, ensure_local_bin_on_path
from ..core.suite import BenchmarkSuite, DBBackend, SuiteConfig, get_suite_config
from ..core.tasks import load_task_for_suite
from ..core.workdir import prepare_sql_workdir, write_sql_claude_md
from ..evaluation.sql_comparator import evaluate_sql

ensure_local_bin_on_path()

_SYSTEM_PROMPT_TEMPLATE: str = (PROMPTS_DIR / "system_general.md").read_text()

_GATEWAY_HTTP = "http://localhost:3300"


def _register_snowflake_http(instance_id: str, database: str, schema: str) -> bool:
    """Register a Snowflake connection via the gateway HTTP API.

    MCP tools like schema_overview hit the gateway's HTTP endpoints, so the
    connection must exist in the gateway's DB, not just the local store file.
    """
    import json
    import urllib.error
    import urllib.request

    try:
        env_vars = _load_dotenv_file(SNOWFLAKE_ENV_FILE)
    except FileNotFoundError:
        log(f"Snowflake env file not found: {SNOWFLAKE_ENV_FILE}", "ERROR")
        return False

    # Delete existing (ignore errors)
    try:
        req = urllib.request.Request(f"{_GATEWAY_HTTP}/api/connections/{instance_id}", method="DELETE")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    payload = json.dumps({
        "name": instance_id,
        "db_type": "snowflake",
        "account": env_vars["SNOWFLAKE_ACCOUNT"],
        "username": env_vars["SNOWFLAKE_USER"],
        "password": env_vars["SNOWFLAKE_TOKEN"],
        "database": database,
        "warehouse": env_vars.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH_PARTICIPANT"),
        "role": env_vars.get("SNOWFLAKE_ROLE", "PARTICIPANT"),
        "schema_name": schema,
    }).encode()

    try:
        req = urllib.request.Request(
            f"{_GATEWAY_HTTP}/api/connections",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        log(f"Registered Snowflake connection '{instance_id}' via HTTP gateway")
        return True
    except Exception as e:
        log(f"HTTP registration failed for '{instance_id}': {e}", "WARN")
        return False

_SUITE_SKILL_NAMES: dict[BenchmarkSuite, tuple[str, ...]] = {
    BenchmarkSuite.SNOWFLAKE: ("sql-workflow", "snowflake-sql"),
    BenchmarkSuite.LITE: ("sql-workflow", "snowflake-sql", "bigquery-sql", "sqlite-sql"),
}


def _determine_backend(suite: BenchmarkSuite, task: dict, config: SuiteConfig) -> DBBackend:
    """Determine the DB backend for a task."""
    if suite == BenchmarkSuite.SNOWFLAKE:
        return DBBackend.SNOWFLAKE

    # If the task has an explicit type field, use it
    task_type = task.get("type")
    if task_type:
        mapping: dict[str, DBBackend] = {
            "sqlite": DBBackend.SQLITE,
            "snowflake": DBBackend.SNOWFLAKE,
            "bigquery": DBBackend.BIGQUERY,
        }
        backend = mapping.get(task_type)
        if backend is None:
            raise ValueError(f"Unknown task type '{task_type}' — expected sqlite/snowflake/bigquery")
        return backend

    # Infer from which resource/databases/<type>/ directory contains the db name
    db_name = task.get("db", "")
    resource_dir = config.data_dir / "resource" / "databases"
    for db_type, backend in [
        ("snowflake", DBBackend.SNOWFLAKE),
        ("bigquery", DBBackend.BIGQUERY),
        ("sqlite", DBBackend.SQLITE),
    ]:
        type_dir = resource_dir / db_type
        if type_dir.exists() and (type_dir / db_name).exists():
            return backend

    # Default to sqlite for backwards compat
    log(f"Could not infer backend for db='{db_name}', defaulting to sqlite", "WARN")
    return DBBackend.SQLITE


def _register_connection(
    instance_id: str,
    backend: DBBackend,
    task: dict,
    work_dir: Path,
    config: SuiteConfig,
) -> bool:
    """Register the appropriate DB connection for the task."""
    if backend == DBBackend.SNOWFLAKE:
        database: str = task.get("db_id", task.get("db", task.get("database", "")))
        schema: str = task.get("schema", task.get("schema_name", "PUBLIC"))
        if not database:
            log(f"Task '{instance_id}' missing 'db_id'/'db'/'database' field for Snowflake", "WARN")
        # Register both locally (for list_tables/query_database) and via HTTP
        # (for schema_overview and other gateway-API-backed MCP tools).
        local_ok = register_snowflake_connection(instance_id, database, schema)
        http_ok = _register_snowflake_http(instance_id, database, schema)
        return local_ok or http_ok  # local is sufficient when gateway isn't running

    if backend == DBBackend.SQLITE:
        db_name: str = task.get("db", task.get("db_id", ""))
        db_path = str(work_dir / f"{db_name}.sqlite") if db_name else str(work_dir)
        return register_sqlite_connection(instance_id, db_path)

    if backend == DBBackend.BIGQUERY:
        project: str = task.get("project_id", task.get("project", ""))
        dataset: str = task.get("dataset", task.get("schema", ""))
        if not project:
            # Spider2-Lite BQ tasks use spider2-public-data project by default
            project = "spider2-public-data"
            log(f"Task '{instance_id}' missing project_id, using default: {project}")
        if not dataset:
            # Use the db field as the dataset name
            dataset = task.get("db", "")
        return register_bigquery_connection(instance_id, project, dataset)

    log(f"Unsupported backend '{backend}' — cannot register connection", "ERROR")
    return False


async def _run_agent(
    instance_id: str,
    instruction: str,
    work_dir: Path,
    db_backend: DBBackend,
    connection_name: str,
    model: str,
    max_turns: int,
    suite: BenchmarkSuite,
) -> bool:
    """Run the SQL agent for this task."""
    log_separator(f"AGENT  model={model}  max_turns={max_turns}  instance={instance_id}")

    prompt = build_sql_agent_prompt(
        instance_id=instance_id,
        instruction=instruction,
        work_dir=work_dir,
        db_backend=db_backend,
        connection_name=connection_name,
        max_turns=max_turns,
    )
    log(f"Prompt length: {len(prompt)} chars")

    system_prompt = (
        _SYSTEM_PROMPT_TEMPLATE
        .replace("${work_dir}", str(work_dir))
        .replace("${instance_id}", instance_id)
        .replace("${connection_name}", connection_name)
    )

    skill_names = _SUITE_SKILL_NAMES.get(suite)

    result = await run_sdk_agent(
        prompt=prompt,
        work_dir=work_dir,
        model=model,
        max_turns=max_turns,
        timeout=900,
        label="sql-agent",
        skill_names=skill_names,
        system_prompt=system_prompt,
    )

    transcript_path = work_dir / "agent_output.json"
    transcript_path.write_text(json.dumps({
        "tool_calls": result["tool_calls"],
        "messages": result["messages"],
        "turns": result["turns"],
    }))

    return result["success"]


def main(suite: BenchmarkSuite) -> None:
    """Entry point for SQL runner, called from run_direct.py with suite routing."""
    parser = argparse.ArgumentParser(
        description=f"Run a {suite.value} task directly using Claude Agent SDK + MCP"
    )
    parser.add_argument("instance_id", help="Task instance ID")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Claude model to use")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help="Safety cap on agent turns. Default 50.",
    )
    parser.add_argument("--skip-agent", action="store_true", help="Skip agent, only evaluate existing results")
    args = parser.parse_args()

    instance_id: str = args.instance_id
    model: str = args.model
    max_turns: int = args.max_turns

    log_separator(f"{suite.value} Direct Benchmark: {instance_id}")
    log(f"Model:     {model}")
    log(f"Max turns: {max_turns}")

    # ── Load suite config ──────────────────────────────────────────────────────
    config = get_suite_config(suite)

    # ── Load task ──────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    task = load_task_for_suite(instance_id, config)
    instruction: str = task.get("instruction") or task.get("question", "")
    if not instruction:
        log(f"Task '{instance_id}' has no 'instruction' or 'question' field", "ERROR")
        sys.exit(1)
    log(f"Task loaded in {time.monotonic()-t0:.2f}s")
    log(f"Instruction: {instruction}")

    # ── Determine DB backend ───────────────────────────────────────────────────
    backend = _determine_backend(suite, task, config)
    log(f"DB backend: {backend.value}")

    work_dir = config.work_dir / instance_id

    if not args.skip_agent:
        # ── Prepare workdir ────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 1: Prepare SQL workdir")
        work_dir = prepare_sql_workdir(instance_id, config, task, backend=backend)
        log(f"Workdir ready in {time.monotonic()-t0:.2f}s")

        # ── Write CLAUDE.md ────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 2: Write CLAUDE.md")
        write_sql_claude_md(work_dir, instance_id, instruction, backend, connection_name=instance_id)
        log(f"CLAUDE.md written in {time.monotonic()-t0:.2f}s")

        # ── Register DB connection ─────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 3: Register DB connection")
        conn_ok = _register_connection(instance_id, backend, task, work_dir, config)
        if not conn_ok:
            log(f"Connection registration failed for '{instance_id}' ({backend.value})", "WARN")
        log(f"Connection registration in {time.monotonic()-t0:.2f}s")

        # ── Run agent ──────────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 4: Run Claude SQL agent")
        try:
            agent_ok = asyncio.run(_run_agent(
                instance_id=instance_id,
                instruction=instruction,
                work_dir=work_dir,
                db_backend=backend,
                connection_name=instance_id,
                model=model,
                max_turns=max_turns,
                suite=suite,
            ))
        except Exception as e:
            log(f"Agent SDK error: {e}", "ERROR")
            agent_ok = False
        elapsed = time.monotonic() - t0
        log(f"Agent finished in {elapsed:.1f}s — {'success' if agent_ok else 'failed/partial'}")

        # ── Fail fast if result.csv is missing ────────────────────────────────
        result_csv = work_dir / "result.csv"
        if not result_csv.exists():
            log(
                f"result.csv not found in {work_dir} — agent did not save output. "
                "This task cannot be evaluated.",
                "ERROR",
            )
            # Delete connection before exiting
            if delete_local_connection(instance_id):
                log(f"Cleaned up connection '{instance_id}'")
            sys.exit(1)

        # ── Delete connection (cleanup, prevent cross-task leakage) ───────────
        if delete_local_connection(instance_id):
            log(f"Released MCP connection '{instance_id}' before evaluation")

    # ── Evaluate ───────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    log_separator("Step 5: Evaluate against gold standard")

    if not work_dir.exists():
        log(f"Work dir not found: {work_dir}", "ERROR")
        log("Run without --skip-agent first to generate results.")
        sys.exit(1)

    result_csv = work_dir / "result.csv"
    if not result_csv.exists():
        log(
            f"result.csv not found in {work_dir}. "
            "Run without --skip-agent to generate results.",
            "ERROR",
        )
        sys.exit(1)

    try:
        passed, details = evaluate_sql(work_dir, instance_id, config)
    except Exception as e:
        import traceback
        log(f"Evaluation error: {e}", "ERROR")
        traceback.print_exc()
        log_separator("RESULT: ERROR")
        sys.exit(1)

    log(f"Evaluation finished in {time.monotonic()-t0:.2f}s")
    print(details)
    log_separator(f"RESULT: {'PASS' if passed else 'FAIL'}")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    # This file should not be run directly; use run_direct.py with --suite
    raise SystemExit("Use: python -m benchmark.run_direct --suite spider2-snowflake <instance_id>")
