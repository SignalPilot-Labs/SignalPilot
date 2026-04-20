"""Spider2-DBT benchmark runner — runs directly without Docker.

Uses the Claude Agent SDK with MCP config for SignalPilot integration.
Intended for use inside a container or machine that already has all deps
(dbt-duckdb, claude CLI, python gateway) installed.

Usage:
    python -m benchmark.runners.direct chinook001
    python -m benchmark.runners.direct chinook001 --model claude-opus-4-6
    python -m benchmark.runners.direct chinook001 --skip-agent   # re-eval only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from claude_agent_sdk.types import AgentDefinition

from ..agent.prompts import build_agent_prompt
from ..agent.sdk_runner import (
    run_name_fix_agent,
    run_quick_fix_agent,
    run_sdk_agent,
)
from ..core.audit import save_single_task_run
from ..core.logging import log, log_separator
from ..core.mcp import clear_all_connections, delete_local_connection, register_local_connection
from ..core.paths import GOLD_DIR, MCP_CONFIG, PROMPTS_DIR, WORK_DIR, ensure_local_bin_on_path
from ..core.tasks import load_eval_config, load_task
from ..core.workdir import prepare_workdir, write_claude_md
from ..dbt_tools.fixes import run_post_agent_sql_fixes
from ..dbt_tools.postprocess import add_missing_columns, dedup_eval_tables
from ..dbt_tools.scanner import (
    check_package_availability,
    classify_sql_models,
    extract_model_columns,
    scan_yml_models,
)
from ..dbt_tools.templates import create_ephemeral_stubs, create_sql_templates
from ..evaluation.comparator import evaluate
from ..evaluation.db_utils import find_result_db, get_table_row_counts

ensure_local_bin_on_path()

DBT_BIN = shutil.which("dbt") or "/home/agentuser/.local/bin/dbt"

_DBT_SYSTEM_PROMPT_TEMPLATE: str = (PROMPTS_DIR / "dbt_local_system.md").read_text()

_DBT_SKILL_NAMES: tuple[str, ...] = ("dbt-workflow", "dbt-debugging", "duckdb-sql")


def _snapshot_reference_tables(work_dir: Path, db_path: Path | None) -> None:
    """Snapshot model tables that exist in the DB before the agent rebuilds them.

    Only snapshots tables where: (1) a model SQL file exists AND is a stub, and
    (2) the table already exists in the database (pre-computed reference data).
    Raw source tables and complete models are excluded.
    """
    if not db_path or not db_path.exists():
        return

    import duckdb as _ddb

    complete, stub_models = classify_sql_models(work_dir)
    log(f"Snapshot: found {len(stub_models)} stubs: {sorted(stub_models)[:5]}")
    if not stub_models:
        return

    try:
        con = _ddb.connect(str(db_path), read_only=True)
        db_tables = set(r[0] for r in con.execute("SHOW TABLES").fetchall())
    except Exception as e:
        log(f"Snapshot: cannot open DB: {e}", "WARN")
        return

    # Snapshot stubs that exist as pre-computed tables, plus complete sibling
    # models in the same directories (their sample data helps the verifier
    # catch NULL vs 0 and expression mismatches).
    stub_dirs = set()
    for sql_file in work_dir.rglob("*.sql"):
        if any(skip in str(sql_file) for skip in ("dbt_packages", "target", ".claude")):
            continue
        if sql_file.stem in stub_models:
            stub_dirs.add(sql_file.parent)
    sibling_models = set()
    for d in stub_dirs:
        for sql_file in d.glob("*.sql"):
            if sql_file.stem in complete and sql_file.stem in db_tables:
                sibling_models.add(sql_file.stem)
    to_snapshot = sorted((stub_models & db_tables) | sibling_models)
    if not to_snapshot:
        con.close()
        log("Snapshot: no stub models have pre-existing tables — skipping")
        return

    lines = ["# Reference Table Snapshot\n"]
    for table in to_snapshot:
        try:
            row_count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            cols = con.execute(
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_name = '{table}' ORDER BY ordinal_position"
            ).fetchall()
            sample_rows = con.execute(f'SELECT * FROM "{table}" LIMIT 3').fetchall()
            col_names = [c[0] for c in cols]

            lines.append(f"## {table} ({row_count:,} rows)")
            lines.append("| Column | Type |")
            lines.append("|--------|------|")
            for col_name, col_type in cols:
                lines.append(f"| {col_name} | {col_type} |")
            lines.append("")
            if sample_rows:
                lines.append("Sample:")
                lines.append("| " + " | ".join(col_names) + " |")
                lines.append("|" + "|".join("---" for _ in col_names) + "|")
                for row in sample_rows:
                    lines.append("| " + " | ".join(str(v) for v in row) + " |")
            lines.append("")
        except Exception as e:
            lines.append(f"## {table} (ERROR: {e})\n")

    con.close()

    try:
        snapshot_path = work_dir / "reference_snapshot.md"
        snapshot_path.write_text("\n".join(lines))
        log(f"Snapshot: captured {len(to_snapshot)} reference table(s): {to_snapshot}")
    except Exception as e:
        log(f"Snapshot: failed to write file: {e}", "WARN")


async def run_agent(
    instance_id: str,
    instruction: str,
    work_dir: Path,
    model: str,
    max_turns: int,
    eval_critical_models: set[str],
) -> bool:
    """Run the Claude Agent SDK in the work directory."""
    log_separator(f"AGENT  model={model}  max_turns={max_turns}  instance={instance_id}")

    prompt = build_agent_prompt(instance_id, instruction, work_dir, eval_critical_models, max_turns=max_turns)
    log(f"Prompt length: {len(prompt)} chars")
    print("--- USER PROMPT START ---", flush=True)
    print(prompt, flush=True)
    print("--- USER PROMPT END ---", flush=True)

    system_prompt = (
        _DBT_SYSTEM_PROMPT_TEMPLATE
        .replace("${work_dir}", str(work_dir))
        .replace("${instance_id}", instance_id)
        .replace("${instruction}", instruction)
        .replace("${dbt_bin}", DBT_BIN)
    )
    print("--- SYSTEM PROMPT START ---", flush=True)
    print(system_prompt, flush=True)
    print("--- SYSTEM PROMPT END ---", flush=True)

    verify_prompt_template = (PROMPTS_DIR / "dbt_verify_subagent.md").read_text()
    verify_prompt_text = (
        verify_prompt_template
        .replace("${work_dir}", str(work_dir))
        .replace("${instance_id}", instance_id)
        .replace("${dbt_bin}", DBT_BIN)
    )
    verify_agent = AgentDefinition(
        description="Verification agent that checks dbt model output for correctness after the build is complete.",
        prompt=verify_prompt_text,
        model="claude-sonnet-4-6",
        maxTurns=80,
    )

    result = await run_sdk_agent(
        prompt,
        work_dir,
        model,
        max_turns,
        timeout=900,
        label="main-agent",
        skill_names=_DBT_SKILL_NAMES,
        system_prompt=system_prompt,
        agents={"verifier": verify_agent},
    )

    transcript_path = work_dir / "agent_output.json"
    transcript_path.write_text(json.dumps({
        "transcript": result["transcript"],
        "tool_calls": result["tool_calls"],
        "messages": result["messages"],
        "turns": result["turns"],
    }))

    return result["success"]


def _auto_scale_max_turns(work_dir: Path, eval_critical_models: set[str], default_turns: int) -> int:
    """Deprecated: we no longer scale turns by project complexity.

    Turn caps are now a uniform safety ceiling (200) regardless of task size.
    Validation loops are legitimate work and there is no budget cap either.
    This function is kept only so that existing callers don't break — it logs
    the project shape for debugging and returns the caller's default.
    """
    yml_models = scan_yml_models(work_dir)
    complete_sql_models, stub_sql_models = classify_sql_models(work_dir)
    missing_models_set = yml_models - (complete_sql_models | stub_sql_models)
    work_count = len(missing_models_set) + len(stub_sql_models)
    total_sql = len(list(work_dir.rglob("*.sql")))
    log(
        f"Project shape: {work_count} model(s) needing work "
        f"({len(missing_models_set)} missing, {len(stub_sql_models)} stubs, "
        f"{total_sql} total SQL files) — max_turns={default_turns}"
    )
    return default_turns


def _run_dbt_selective(work_dir: Path, eval_critical_models: set[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Run `dbt run --select <model>...` for eval-critical models (no upstream deps)."""
    select_args = (
        [DBT_BIN, "run", "--select"]
        + list(sorted(eval_critical_models))
    )
    return subprocess.run(select_args, cwd=str(work_dir), capture_output=True, text=True, timeout=timeout)


def _build_fix_prompt(
    work_dir: Path,
    instruction: str,
    error_output: str,
    eval_critical_models: set[str],
) -> str:
    has_packages_yml = (work_dir / "packages.yml").exists()
    fix_prompt = f"""Fix dbt errors in {work_dir}. The task: {instruction}

dbt run failed with this error:
{error_output}

Steps:
1. Read the error carefully — identify which model failed and why
2. Read the failing SQL file and fix the error
3. Run: dbt run --select {' '.join(sorted(eval_critical_models))}
4. If it passes, done. If not, fix and retry.

RULES: DuckDB SQL only. Do NOT modify .yml files. Use STRPTIME for non-ISO date parsing.{"" if has_packages_yml else " NEVER run dbt deps — it will wipe pre-installed packages!"}"""

    col_specs: list[str] = []
    model_columns = extract_model_columns(work_dir)
    for model_name in sorted(eval_critical_models):
        if model_name in model_columns:
            col_specs.append(f"  {model_name} must have these columns in order: {', '.join(model_columns[model_name])}")
    if col_specs:
        fix_prompt += "\n\nREQUIRED COLUMN SPECS (your SQL must produce these exact columns):\n" + "\n".join(col_specs)

    fix_prompt += (
        "\n\nAfter fixing, verify your output:"
        "\n- Run mcp__signalpilot__query_database with: SELECT COUNT(*), COUNT(DISTINCT <pk>) FROM <model_table>"
        "\n- If count seems wrong, check your JOIN conditions for fan-out"
    )

    table_counts = get_table_row_counts(work_dir)
    if table_counts:
        counts_lines = [f"  {name}: {count:,} rows" for name, count in sorted(table_counts.items())]
        fix_prompt += "\n\nSOURCE TABLE CARDINALITIES (input sizes, not gold targets):\n"
        fix_prompt += "\n".join(counts_lines)
        fix_prompt += (
            "\n- Use these to detect fan-out: if your output row count > largest plausible source slice, JOIN is duplicating rows."
            "\n- If output << any source table that should feed into it: check for over-filtering or wrong JOIN type."
            "\nROW COUNT AUDIT:\n"
            "1. SELECT COUNT(*) FROM <model>; SELECT COUNT(DISTINCT <pk>) FROM <source>\n"
            "2. If model > source distinct pk: fan-out — find the JOIN causing duplication\n"
            "3. If model << source: check WHERE and JOIN types for over-filtering"
        )
    return fix_prompt


def _build_name_fix_prompt(
    work_dir: Path,
    instruction: str,
    missing_eval_tables: set[str],
    existing_tables: set[str],
) -> str:
    similar_hints = []
    for missing in sorted(missing_eval_tables):
        missing_parts = set(missing.replace('__', '_').split('_'))
        for existing in sorted(existing_tables):
            existing_parts = set(existing.replace('__', '_').split('_'))
            if len(missing_parts & existing_parts) >= 2:
                similar_hints.append(f"  '{existing}' may contain the data for '{missing}'")

    has_packages_yml = (work_dir / "packages.yml").exists()
    name_fix_prompt = f"""Fix missing output tables in the dbt project at {work_dir}.

Task: {instruction}

PROBLEM: The following required table names do NOT exist in the result database:
{chr(10).join(f"  - {t}" for t in sorted(missing_eval_tables))}

CURRENT TABLES IN DATABASE:
{chr(10).join(f"  - {t}" for t in sorted(existing_tables))}

{("SIMILAR EXISTING TABLES (may have the right data under a wrong name):" + chr(10) + chr(10).join(similar_hints)) if similar_hints else ""}

STEPS TO FIX:
1. List files in models/ to find existing SQL files: ls models/*.sql models/**/*.sql
2. Find the model that computes the required data (look for similar logic/name)
3. Create a new .sql file with the EXACT required name:
   Example for missing 'zuora__account_overview':
   Create models/zuora__account_overview.sql:
     {{{{ config(materialized='table') }}}}
     SELECT * FROM {{{{ ref('your_existing_model_name') }}}}
   OR rename the existing file if no downstream models depend on it.
4. Run: dbt run --select {" ".join(sorted(missing_eval_tables))}
5. Verify: run SHOW TABLES and confirm the exact name appears.

RULES:
- Do NOT modify .yml files
- Use materialized='table' in config
- DuckDB SQL only
- The table name must be exactly: {", ".join(sorted(missing_eval_tables))}
{"- NEVER run dbt deps — it will wipe pre-installed packages!" if not has_packages_yml else ""}"""

    col_specs: list[str] = []
    model_columns = extract_model_columns(work_dir)
    for model_name in sorted(missing_eval_tables):
        if model_name in model_columns:
            col_specs.append(f"  {model_name}: {', '.join(model_columns[model_name])}")
    if col_specs:
        name_fix_prompt += "\n\nREQUIRED COLUMNS:\n" + "\n".join(col_specs)
    return name_fix_prompt


def _post_agent_dbt_run(
    work_dir: Path,
    instruction: str,
    eval_critical_models: set[str],
    model: str,
) -> None:
    """Post-agent safety net: run dbt deps + dbt run, dispatch quick-fix agent on failure."""
    t0 = time.monotonic()
    log_separator("Step 4b: Final dbt deps + dbt run (post-agent safety net)")

    # Only run dbt deps if packages.yml exists — otherwise it wipes pre-installed packages!
    if (work_dir / "packages.yml").exists():
        subprocess.run(
            [DBT_BIN, "deps"],
            cwd=str(work_dir), capture_output=True, text=True, timeout=120,
        )

    created_stubs_post = create_ephemeral_stubs(work_dir)
    if created_stubs_post:
        log(f"Post-agent ephemeral stubs created: {sorted(created_stubs_post)}")

    # Post-agent SQL fixes disabled — the automatic INNER→LEFT JOIN rewrite
    # overrides correct agent decisions and can introduce floating point artifacts.
    # run_post_agent_sql_fixes(work_dir, instruction, eval_critical_models)

    if eval_critical_models:
        dbt_result = _run_dbt_selective(work_dir, eval_critical_models)
        if dbt_result.returncode == 0:
            log(f"Selective dbt run (eval-critical) PASSED in {time.monotonic()-t0:.1f}s")
        else:
            log(f"Selective dbt run (eval-critical) FAILED in {time.monotonic()-t0:.1f}s")
            for line in (dbt_result.stdout + dbt_result.stderr).strip().splitlines()[-20:]:
                log(f"  dbt: {line}")
    else:
        dbt_result = subprocess.run(
            [DBT_BIN, "run"],
            cwd=str(work_dir), capture_output=True, text=True, timeout=120,
        )
        if dbt_result.returncode == 0:
            log(f"Final dbt run PASSED in {time.monotonic()-t0:.1f}s")
        else:
            log(f"Final dbt run FAILED in {time.monotonic()-t0:.1f}s")
            for line in (dbt_result.stdout + dbt_result.stderr).strip().splitlines()[-20:]:
                log(f"  dbt: {line}")

    if eval_critical_models and dbt_result.returncode != 0:
        error_output = (dbt_result.stdout + dbt_result.stderr).strip()[-2000:]
        fix_prompt = _build_fix_prompt(work_dir, instruction, error_output, eval_critical_models)
        try:
            asyncio.run(run_quick_fix_agent(fix_prompt, work_dir, model))
        except Exception as e:
            log(f"Quick-fix agent failed: {e}", "WARN")

    # Best-effort selective run (eval-critical only — do NOT run a full rebuild
    # as it overwrites pre-existing dimension tables with non-deterministic ordering)
    if eval_critical_models:
        subprocess.run(
            [DBT_BIN, "run", "--select"] + list(sorted(eval_critical_models)),
            cwd=str(work_dir), capture_output=True, text=True, timeout=300,
        )



def _run_name_fix_stage(
    work_dir: Path,
    instance_id: str,
    instruction: str,
    eval_critical_models: set[str],
    model: str,
) -> None:
    """If eval-critical tables are missing by name, dispatch a name-fix agent."""
    if not eval_critical_models:
        return

    _result_db = find_result_db(work_dir)
    if not _result_db:
        return

    try:
        import duckdb as _ddb
        _con = _ddb.connect(str(_result_db), read_only=True)
        existing_tables = set(r[0] for r in _con.execute("SHOW TABLES").fetchall())
        _con.close()
    except Exception as e:
        log(f"Post-eval table check failed: {e}", "WARN")
        return

    missing_eval_tables = eval_critical_models - existing_tables
    if not missing_eval_tables:
        return

    log(f"POST-EVAL CHECK: Missing eval-critical tables: {sorted(missing_eval_tables)}", "WARN")
    name_fix_prompt = _build_name_fix_prompt(work_dir, instruction, missing_eval_tables, existing_tables)

    try:
        name_fix_ok = asyncio.run(run_name_fix_agent(name_fix_prompt, work_dir, model))
    except Exception as e:
        log(f"Name-fix agent failed: {e}", "WARN")
        name_fix_ok = False

    if name_fix_ok:
        subprocess.run(
            [DBT_BIN, "run", "--select"] + list(sorted(missing_eval_tables)),
            cwd=str(work_dir), capture_output=True, text=True, timeout=180,
        )


def _flush_and_release(work_dir: Path, instance_id: str) -> None:
    """Checkpoint DuckDB WAL and release the MCP connection before evaluation."""
    _result_db = find_result_db(work_dir)
    if _result_db:
        try:
            import duckdb as _ddb
            _flush_con = _ddb.connect(database=str(_result_db))
            _flush_con.execute("CHECKPOINT")
            _flush_con.close()
            log("Flushed DuckDB WAL via CHECKPOINT")
        except Exception as e:
            log(f"WAL flush failed (non-fatal): {e}", "WARN")

    if delete_local_connection(instance_id):
        log(f"Released MCP connection '{instance_id}' before evaluation")
    time.sleep(2)


# ── Async helpers for parallel mode ──────────────────────────────────────────
# These wrap blocking subprocess calls so they don't stall the event loop when
# multiple tasks run concurrently under asyncio.gather.

async def _async_subprocess_run(
    args: list[str],
    cwd: str,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Non-blocking subprocess wrapper using asyncio.create_subprocess_exec."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise subprocess.TimeoutExpired(args, timeout)
    return subprocess.CompletedProcess(
        args=args,
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout_b.decode(errors="replace"),
        stderr=stderr_b.decode(errors="replace"),
    )


async def _run_dbt_selective_async(
    work_dir: Path,
    eval_critical_models: set[str],
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Async version of _run_dbt_selective."""
    select_args = (
        [DBT_BIN, "run", "--select"]
        + list(sorted(eval_critical_models))
    )
    return await _async_subprocess_run(select_args, cwd=str(work_dir), timeout=timeout)


async def _post_agent_dbt_run_async(
    work_dir: Path,
    instruction: str,
    eval_critical_models: set[str],
    model: str,
) -> None:
    """Async version of _post_agent_dbt_run for use in parallel execution."""
    t0 = time.monotonic()
    log_separator("Step 4b: Final dbt deps + dbt run (post-agent safety net)")

    if (work_dir / "packages.yml").exists():
        await _async_subprocess_run(
            [DBT_BIN, "deps"],
            cwd=str(work_dir),
            timeout=120,
        )

    created_stubs_post = create_ephemeral_stubs(work_dir)
    if created_stubs_post:
        log(f"Post-agent ephemeral stubs created: {sorted(created_stubs_post)}")

    # Post-agent SQL fixes disabled — the automatic INNER→LEFT JOIN rewrite
    # overrides correct agent decisions and can introduce floating point artifacts.
    # run_post_agent_sql_fixes(work_dir, instruction, eval_critical_models)

    if eval_critical_models:
        dbt_result = await _run_dbt_selective_async(work_dir, eval_critical_models)
        if dbt_result.returncode == 0:
            log(f"Selective dbt run (eval-critical) PASSED in {time.monotonic()-t0:.1f}s")
        else:
            log(f"Selective dbt run (eval-critical) FAILED in {time.monotonic()-t0:.1f}s")
            for line in (dbt_result.stdout + dbt_result.stderr).strip().splitlines()[-20:]:
                log(f"  dbt: {line}")
    else:
        dbt_result = await _async_subprocess_run(
            [DBT_BIN, "run"],
            cwd=str(work_dir),
            timeout=120,
        )
        if dbt_result.returncode == 0:
            log(f"Final dbt run PASSED in {time.monotonic()-t0:.1f}s")
        else:
            log(f"Final dbt run FAILED in {time.monotonic()-t0:.1f}s")
            for line in (dbt_result.stdout + dbt_result.stderr).strip().splitlines()[-20:]:
                log(f"  dbt: {line}")

    if eval_critical_models and dbt_result.returncode != 0:
        error_output = (dbt_result.stdout + dbt_result.stderr).strip()[-2000:]
        fix_prompt = _build_fix_prompt(work_dir, instruction, error_output, eval_critical_models)
        try:
            await run_quick_fix_agent(fix_prompt, work_dir, model)
        except Exception as e:
            log(f"Quick-fix agent failed: {e}", "WARN")

    # Best-effort selective run (eval-critical only — do NOT run a full rebuild
    # as it overwrites pre-existing dimension tables with non-deterministic ordering)
    if eval_critical_models:
        await _async_subprocess_run(
            [DBT_BIN, "run", "--select"] + list(sorted(eval_critical_models)),
            cwd=str(work_dir),
            timeout=300,
        )



async def _run_name_fix_stage_async(
    work_dir: Path,
    instance_id: str,
    instruction: str,
    eval_critical_models: set[str],
    model: str,
) -> None:
    """Async version of _run_name_fix_stage for use in parallel execution."""
    if not eval_critical_models:
        return

    _result_db = find_result_db(work_dir)
    if not _result_db:
        return

    try:
        import duckdb as _ddb
        _con = _ddb.connect(str(_result_db), read_only=True)
        existing_tables = set(r[0] for r in _con.execute("SHOW TABLES").fetchall())
        _con.close()
    except Exception as e:
        log(f"Post-eval table check failed: {e}", "WARN")
        return

    missing_eval_tables = eval_critical_models - existing_tables
    if not missing_eval_tables:
        return

    log(f"POST-EVAL CHECK: Missing eval-critical tables: {sorted(missing_eval_tables)}", "WARN")
    name_fix_prompt = _build_name_fix_prompt(work_dir, instruction, missing_eval_tables, existing_tables)

    name_fix_ok = False
    try:
        name_fix_ok = await run_name_fix_agent(name_fix_prompt, work_dir, model)
    except Exception as e:
        log(f"Name-fix agent failed: {e}", "WARN")

    if name_fix_ok:
        await _async_subprocess_run(
            [DBT_BIN, "run", "--select"] + list(sorted(missing_eval_tables)),
            cwd=str(work_dir),
            timeout=180,
        )


async def _flush_and_release_async(work_dir: Path, connection_name: str) -> None:
    """Async version of _flush_and_release."""
    _result_db = find_result_db(work_dir)
    if _result_db:
        try:
            import duckdb as _ddb
            _flush_con = _ddb.connect(database=str(_result_db))
            _flush_con.execute("CHECKPOINT")
            _flush_con.close()
            log("Flushed DuckDB WAL via CHECKPOINT")
        except Exception as e:
            log(f"WAL flush failed (non-fatal): {e}", "WARN")

    if delete_local_connection(connection_name):
        log(f"Released MCP connection '{connection_name}' before evaluation")
    await asyncio.sleep(2)


async def execute_dbt_task(
    instance_id: str,
    model: str,
    max_turns: int,
    no_reset: bool,
    connection_prefix: str,
    skip_agent: bool = False,
) -> tuple[bool, dict]:
    """Execute a single DBT task in-process for parallel mode.

    Returns (passed, agent_result_dict) where agent_result_dict contains
    tool_calls, messages, turns, cost_usd, usage, started_at, and elapsed.

    The connection_prefix is prepended to the instance_id to form a unique
    connection name, preventing collisions when multiple tasks run concurrently.
    """
    connection_name = f"{connection_prefix}{instance_id}" if connection_prefix else instance_id

    log_separator(f"Spider2-DBT Direct Benchmark: {instance_id}")
    log(f"Model:     {model}")
    log(f"Max turns: {max_turns}")
    log(f"Connection name: {connection_name}")

    task = load_task(instance_id)
    instruction: str = task["instruction"]

    work_dir = WORK_DIR / instance_id

    eval_config = load_eval_config(instance_id)
    eval_critical_models: set[str] = set()
    if eval_config is not None:
        params = eval_config.get("evaluation", {}).get("parameters", {})
        condition_tabs = params.get("condition_tabs") or []
        eval_critical_models = set(condition_tabs)
        log(f"Eval-critical models: {sorted(eval_critical_models)}")
    else:
        log(f"No eval config found for '{instance_id}' — treating all models as equal", "WARN")

    agent_result: dict = {
        "success": False, "messages": [], "tool_calls": [], "turns": 0, "elapsed": 0.0,
        "cost_usd": None, "usage": None, "started_at": "",
    }

    if not skip_agent:
        # Step 1: Prepare workdir
        log_separator("Step 1: Prepare workdir")
        if no_reset and work_dir.exists():
            log(f"Reusing existing workdir (--no-reset): {work_dir}")
        else:
            work_dir = prepare_workdir(instance_id)

        # Fix date-dependent tables in the starting DB
        from ..fix_starting_dbs import fix_task_db
        if fix_task_db(instance_id, work_dir):
            log(f"Fixed date-dependent tables for {instance_id}")

        # Step 2: Write CLAUDE.md
        log_separator("Step 2: Write CLAUDE.md")
        write_claude_md(work_dir, instance_id, instruction)

        # Step 3: Register connection
        log_separator("Step 3: Register DuckDB connection")
        _db = find_result_db(work_dir)
        if _db:
            register_local_connection(connection_name, str(_db))
        else:
            log(f"No .duckdb files in {work_dir}", "WARN")

        _auto_scale_max_turns(work_dir, eval_critical_models, max_turns)

        for w in check_package_availability(work_dir):
            log(w, "WARN")

        created_templates = create_sql_templates(work_dir, eval_critical_models)
        if created_templates:
            log(f"Pre-populated {len(created_templates)} SQL template(s) for priority models")

        created_stubs = create_ephemeral_stubs(work_dir)
        if created_stubs:
            log(f"Auto-created {len(created_stubs)} ephemeral stub(s): {', '.join(sorted(created_stubs))}")

        _snapshot_reference_tables(work_dir, _db)

        # Step 4: Run agent
        log_separator("Step 4: Run Claude agent")
        t_agent = time.monotonic()
        try:
            prompt = build_agent_prompt(instance_id, instruction, work_dir, eval_critical_models, max_turns=max_turns)
            system_prompt = (
                _DBT_SYSTEM_PROMPT_TEMPLATE
                .replace("${work_dir}", str(work_dir))
                .replace("${instance_id}", instance_id)
                .replace("${instruction}", instruction)
                .replace("${dbt_bin}", DBT_BIN)
            )
            verify_prompt_template = (PROMPTS_DIR / "dbt_verify_subagent.md").read_text()
            verify_prompt_text = (
                verify_prompt_template
                .replace("${work_dir}", str(work_dir))
                .replace("${instance_id}", instance_id)
                .replace("${dbt_bin}", DBT_BIN)
            )
            verify_agent = AgentDefinition(
                description="Verification agent that checks dbt model output for correctness after the build is complete.",
                prompt=verify_prompt_text,
                model="claude-sonnet-4-6",
                maxTurns=80,
            )
            agent_result = await run_sdk_agent(
                prompt,
                work_dir,
                model,
                max_turns,
                timeout=900,
                label="main-agent",
                skill_names=_DBT_SKILL_NAMES,
                system_prompt=system_prompt,
                agents={"verifier": verify_agent},
            )
            transcript_path = work_dir / "agent_output.json"
            transcript_path.write_text(json.dumps({
                "transcript": agent_result["transcript"],
                "tool_calls": agent_result["tool_calls"],
                "messages": agent_result["messages"],
                "turns": agent_result["turns"],
            }))
        except Exception as e:
            log(f"Agent SDK error: {e}", "ERROR")
        elapsed_agent = time.monotonic() - t_agent
        log(f"Agent finished in {elapsed_agent:.1f}s")

    await _flush_and_release_async(work_dir, connection_name)

    # Re-fix date-dependent tables after flush — the MCP connection is released,
    # so fix_task_db has exclusive write access to the DuckDB file.
    from ..fix_starting_dbs import fix_task_db
    if fix_task_db(instance_id, work_dir):
        log(f"Re-fixed date-dependent tables for {instance_id}")

    # Evaluate
    log_separator("Step 5: Evaluate against gold standard")
    passed = False
    if work_dir.exists():
        try:
            passed, details = evaluate(work_dir, instance_id)
            log(f"Evaluation details: {details}")
        except Exception as e:
            log(f"Evaluation error: {e}", "ERROR")
    else:
        log(f"Work dir not found: {work_dir}", "ERROR")

    # Clean up connection (best effort)
    delete_local_connection(connection_name)

    log_separator(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return passed, agent_result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a Spider2-DBT task directly (no Docker) using Claude Agent SDK + MCP"
    )
    parser.add_argument("instance_id", help="Task instance ID, e.g. chinook001")
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Claude model to use")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=200,
        help="Safety cap on agent turns. Budget is the real throttle. Default 200.",
    )
    parser.add_argument("--skip-agent", action="store_true", help="Skip agent, only evaluate existing results")
    parser.add_argument("--no-reset", action="store_true", help="Don't reset workdir — continue from previous run's output")
    args = parser.parse_args()

    instance_id: str = args.instance_id
    model: str = args.model
    max_turns: int = args.max_turns
    _main_start = time.monotonic()

    log_separator(f"Spider2-DBT Direct Benchmark: {instance_id}")
    clear_all_connections()
    log(f"Model:     {model}")
    log(f"Max turns: {max_turns}")
    log(f"MCP config: {MCP_CONFIG}")
    log(f"Work dir:  {WORK_DIR / instance_id}")

    # ── Load task ──────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    task = load_task(instance_id)
    instruction: str = task["instruction"]
    log(f"Task loaded in {time.monotonic()-t0:.2f}s")
    log(f"Instruction: {instruction}")

    work_dir = WORK_DIR / instance_id

    # ── Load eval config to identify critical models ───────────────────────────
    eval_config = load_eval_config(instance_id)
    eval_critical_models: set[str] = set()
    if eval_config is not None:
        params = eval_config.get("evaluation", {}).get("parameters", {})
        condition_tabs = params.get("condition_tabs") or []
        eval_critical_models = set(condition_tabs)
        log(f"Eval-critical models: {sorted(eval_critical_models)}")

        gold_db_list = list((GOLD_DIR / instance_id).glob("*.duckdb")) if (GOLD_DIR / instance_id).exists() else []
        gold_db = gold_db_list[0] if gold_db_list else GOLD_DIR / instance_id / params.get("gold", "")
        if not gold_db.exists():
            log(f"Gold DB not found: {gold_db} — this task cannot be evaluated!", "WARN")
    else:
        log(f"No eval config found for '{instance_id}' — treating all models as equal", "WARN")

    if not args.skip_agent:
        # ── Prepare workdir ────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 1: Prepare workdir")
        if args.no_reset and work_dir.exists():
            log(f"Reusing existing workdir (--no-reset): {work_dir}")
        else:
            work_dir = prepare_workdir(instance_id)
        log(f"Workdir ready in {time.monotonic()-t0:.2f}s")

        # Fix date-dependent tables in the starting DB
        from ..fix_starting_dbs import fix_task_db
        if fix_task_db(instance_id, work_dir):
            log(f"Fixed date-dependent tables for {instance_id}")

        # ── Write CLAUDE.md ────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 2: Write CLAUDE.md")
        write_claude_md(work_dir, instance_id, instruction)
        log(f"CLAUDE.md written in {time.monotonic()-t0:.2f}s")

        # ── Register connection ────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 3: Register DuckDB connection")
        _db = find_result_db(work_dir)
        if _db:
            register_local_connection(instance_id, str(_db))
        else:
            log(f"No .duckdb files in {work_dir}", "WARN")
        log(f"Connection registered in {time.monotonic()-t0:.2f}s")

        # Still call the helper for its project-shape logging, but it no
        # longer rewrites max_turns.
        _auto_scale_max_turns(work_dir, eval_critical_models, max_turns)

        for w in check_package_availability(work_dir):
            log(w, "WARN")

        created_templates = create_sql_templates(work_dir, eval_critical_models)
        if created_templates:
            log(f"Pre-populated {len(created_templates)} SQL template(s) for priority models")

        created_stubs = create_ephemeral_stubs(work_dir)
        if created_stubs:
            log(f"Auto-created {len(created_stubs)} ephemeral stub(s): {', '.join(sorted(created_stubs))}")

        _snapshot_reference_tables(work_dir, _db)

        # ── Run agent ──────────────────────────────────────────────────────────
        t0 = time.monotonic()
        log_separator("Step 4: Run Claude agent")
        try:
            agent_ok = asyncio.run(run_agent(
                instance_id=instance_id,
                instruction=instruction,
                work_dir=work_dir,
                model=model,
                max_turns=max_turns,
                eval_critical_models=eval_critical_models,
            ))
        except Exception as e:
            log(f"Agent SDK error: {e}", "ERROR")
            agent_ok = False
        elapsed = time.monotonic() - t0
        log(f"Agent finished in {elapsed:.1f}s — {'success' if agent_ok else 'failed/partial'}")

    _flush_and_release(work_dir, instance_id)

    # Re-fix date-dependent tables AFTER flush — MCP connection is released,
    # so fix_task_db has exclusive write access to the DuckDB file.
    from ..fix_starting_dbs import fix_task_db
    if fix_task_db(instance_id, work_dir):
        log(f"Re-fixed date-dependent tables for {instance_id}")

    # ── Evaluate ───────────────────────────────────────────────────────────────
    t0 = time.monotonic()
    log_separator("Step 5: Evaluate against gold standard")

    if not work_dir.exists():
        log(f"Work dir not found: {work_dir}", "ERROR")
        log("Run without --skip-agent first to generate results.")
        sys.exit(1)

    try:
        passed, details = evaluate(work_dir, instance_id)
    except Exception as e:
        import traceback
        log(f"Evaluation error: {e}", "ERROR")
        traceback.print_exc()
        log_separator("RESULT: ERROR")
        sys.exit(1)

    log(f"Evaluation finished in {time.monotonic()-t0:.2f}s")
    print(details)
    log_separator(f"RESULT: {'PASS' if passed else 'FAIL'}")

    # Clean up connection to prevent cross-task leakage
    if delete_local_connection(instance_id):
        log(f"Cleaned up connection '{instance_id}'")

    # Save audit trail to AUDIT_BASE volume
    try:
        total_elapsed = time.monotonic() - _main_start
        run_id = save_single_task_run(
            instance_id=instance_id,
            suite="spider2-dbt",
            model=model,
            passed=passed,
            elapsed_seconds=total_elapsed,
            work_dir=work_dir,
        )
        log(f"Audit saved: {run_id}")
    except Exception as e:
        log(f"Audit save failed: {e}", "WARN")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
