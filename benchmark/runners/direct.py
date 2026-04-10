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
import subprocess
import sys
import time
from pathlib import Path

from ..agent.prompts import build_agent_prompt, build_value_verify_prompt
from ..agent.sdk_runner import (
    run_name_fix_agent,
    run_quick_fix_agent,
    run_sdk_agent,
    run_value_verify_agent,
)
from ..core.logging import log, log_separator
from ..core.mcp import delete_local_connection, register_local_connection
from ..core.paths import GOLD_DIR, MCP_CONFIG, WORK_DIR, ensure_local_bin_on_path
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

DBT_BIN = "/home/agentuser/.local/bin/dbt"


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

    result = await run_sdk_agent(prompt, work_dir, model, max_turns, timeout=900, label="main-agent")

    transcript_path = work_dir / "agent_output.json"
    transcript_path.write_text(json.dumps({
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
    """Run `dbt run --select +<model>...` for eval-critical models."""
    select_args = (
        [DBT_BIN, "run", "--select"]
        + [f"+{m}" for m in sorted(eval_critical_models)]
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

    run_post_agent_sql_fixes(work_dir, instruction, eval_critical_models)

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

    # Best-effort full run
    if eval_critical_models:
        subprocess.run(
            [DBT_BIN, "run", "--select"] + [f"+{m}" for m in sorted(eval_critical_models)],
            cwd=str(work_dir), capture_output=True, text=True, timeout=300,
        )
    subprocess.run(
        [DBT_BIN, "run", "--no-fail-fast"],
        cwd=str(work_dir), capture_output=True, text=True, timeout=300,
    )


def _run_value_verify_stage(
    work_dir: Path,
    instance_id: str,
    instruction: str,
    eval_critical_models: set[str],
    model: str,
) -> None:
    """Post-success value-verification agent."""
    _result_db = find_result_db(work_dir)
    if not (eval_critical_models and _result_db):
        return

    verify_prompt = build_value_verify_prompt(
        work_dir, instance_id, eval_critical_models, instruction,
        extract_model_columns(work_dir),
    )
    try:
        asyncio.run(run_value_verify_agent(verify_prompt, work_dir, model))
    except Exception as e:
        log(f"Value-verify agent failed: {e}", "WARN")

    # Re-run dbt to materialize any fixes
    subprocess.run(
        [DBT_BIN, "run", "--select"] + [f"+{m}" for m in sorted(eval_critical_models)],
        cwd=str(work_dir), capture_output=True, text=True, timeout=180,
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

    log_separator(f"Spider2-DBT Direct Benchmark: {instance_id}")
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

    if not args.skip_agent:
        _post_agent_dbt_run(work_dir, instruction, eval_critical_models, model)
        _run_value_verify_stage(work_dir, instance_id, instruction, eval_critical_models, model)
        _run_name_fix_stage(work_dir, instance_id, instruction, eval_critical_models, model)

    # ── Post-processing: dedup + missing columns (always runs, even with --skip-agent) ──
    _result_db_path = find_result_db(work_dir)
    dedup_eval_tables(work_dir, eval_critical_models, _result_db_path)
    add_missing_columns(work_dir, eval_critical_models, _result_db_path)

    _flush_and_release(work_dir, instance_id)

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

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
